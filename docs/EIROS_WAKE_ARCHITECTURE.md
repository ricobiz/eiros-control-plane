# EIROS Wake Architecture

Этот документ фиксирует рабочую архитектуру пробуждения ChatGPT/EIROS из EIROS MCP widgets, чтобы не терять контекст между ветками ChatGPT и при подключении других моделей, например Claude/Fable.

## 1. Главная идея

ChatGPT не слушает VPS в фоне напрямую. Пробуждение работает только если в текущем ChatGPT-чате уже открыт живой MCP App iframe/widget. Именно этот iframe имеет доступ к host bridge ChatGPT и может вставить новое user-сообщение обратно в текущий чат.

Рабочие каналы пробуждения:

1. Immediate operator wake из UI-виджета, когда Rico пишет прямо в EIROS Room / Control Pill.
2. Background Pulse wake из маленького Listener/Pulse widget, когда событие пришло от Claude, scheduler или VPS.

Оба канала нужны. Это разные механизмы, и их нельзя смешивать в один lifecycle.

## 2. Immediate operator wake

Это самый быстрый и исторически рабочий путь.

Цепочка:

```text
Rico пишет в EIROS Room / Control Pill input
  ↓
widget вызывает MCP tool operator_send(...)
  ↓
server сохраняет addressed collab message в EIROS Hub
  ↓
тот же widget вызывает localWake(result)
  ↓
localWake вставляет wake prompt в текущий ChatGPT chat через bridge
  ↓
ChatGPT получает новое user-сообщение
  ↓
модель просыпается и делает ход
```

Вызов из widget:

```js
callTool('operator_send', {
  content: text,
  target: 'both',
  project_id: 'eiros-hub',
  thread_id: 'first-contact',
  kind: 'operator',
  metadata: {
    source: 'control-pill',
    request_immediate_wake: true
  }
})
```

После успешного `operator_send`, widget обязан сделать immediate local wake, а не ждать Pulse:

```text
[EIROS_OPERATOR_WAKE message_id=<message_id> event_id=<event_id>]
Rico wrote into the EIROS widget. Claim through dialog_inbox as chatgpt, handle it, then dialog_ack. If event_id is present, ack_event after handling.
```

Host bridge варианты:

```js
window.openai.sendMessage(...)
window.mcp.sendMessage(...)
window.openai.sendFollowUpMessage({ prompt, scrollToBottom: true })
window.mcp.sendFollowUpMessage({ prompt, scrollToBottom: true })
window.parent.postMessage({ jsonrpc: '2.0', method: 'ui/message', params: ... }, '*')
```

Исторически работавший старый механизм использовал `bridge.sendMessage(...)` и fallback `ui/message`.

## 3. Background Pulse wake

Это путь для Claude, scheduler, VPS и любых событий, которые уже лежат в durable event queue.

Цепочка:

```text
Claude / server / scheduler создаёт event_engine.emit(...)
  ↓
events.json получает pending event
  ↓
маленький Listener / Pulse Anchor iframe делает pulse_poll(...)
  ↓
получает event
  ↓
вставляет [EIROS_REMOTE_EVENT ...] в текущий ChatGPT chat
  ↓
ChatGPT просыпается
```

Пример wake prompt:

```text
[EIROS_REMOTE_EVENT id=<event_id> seq=<seq> source=collab:claude]
EIROS_HUB_WAKE message_id=<message_id> from=claude project_id=eiros-hub thread_id=first-contact.
...
Handle this event, then call ack_event.
```

Pulse Listener должен оставаться живым даже если открывается/закрывается Room или Control Pill.

## 4. Lifecycle: UI widgets vs wake listener

Нельзя, чтобы Room / Control Pill и Pulse Listener убивали друг друга одним localStorage key.

Правильное разделение:

```text
Room / Control Pill / old Launcher = UI widgets
Pulse Anchor / Wake Listener       = background wake antenna
```

Правильные keys:

```text
eiros-ui-kill:<project>:<thread>
  гасит только UI-карточки: Room, Control Pill, старый Launcher

 e i r o s - w a k e - l i s t e n e r - a c t i v e:<project>:<thread>:<agent>:<channel>
  singleton только для wake listener

eiros-wake-listener-kill:<project>:<thread>
  аварийно гасит только listener
```

Обычный `open_control_pill` не должен писать в listener kill key. Он может закрывать старые UI-карточки, но не имеет права убивать Pulse Anchor.

## 5. Что ChatGPT/EIROS должен делать после wake

После wake-сообщения модель не должна просто отвечать обычным текстом.

Правильный порядок:

1. Вызвать `dialog_inbox(agent_id='chatgpt', project_id='eiros-hub', thread_id='first-contact')`.
2. Найти addressed message по `message_id` / `collab_message_id`, если он указан.
3. Обработать сообщение.
4. При необходимости ответить через `dialog_send(...)`.
5. Закрыть исходное collab-сообщение через `dialog_ack(...)`.
6. Если wake был Pulse event, закрыть event через `ack_event(...)`.

## 6. Критичные условия работоспособности

- В текущем ChatGPT-чате должен быть живой iframe/widget.
- Для immediate wake widget должен вызывать `localWake(...)` сразу после `operator_send(...)`.
- Для background wake должен жить отдельный Listener/Pulse iframe.
- `open_control_pill` не должен убивать Pulse Anchor.
- `pulse_mark_delivered` допустим только после фактической попытки доставки в ChatGPT host bridge.
- `lastEvent` / throttling не должны превращать retry в одноразовый edge-trigger, если wake не дошёл.
- Новые MCP tools/resources не подтягиваются ChatGPT автоматически после изменения server code; connector нужно физически переподключать в ChatGPT UI.
- iOS ChatGPT app может держать iframe/resource/tool schema cache. Иногда нужен branch switch / web reconnect / второй прогревочный вызов.

## 7. AppDeploy не является wake-механизмом

AppDeploy может показывать внешний веб-интерфейс, но он не вставляет сообщения в текущий ChatGPT chat. Рабочее пробуждение происходит именно из MCP App iframe, потому что он смонтирован внутри ChatGPT и имеет host bridge.

## 8. Current target state

```text
open_pulse
  → ставит background Wake Listener / Pulse Anchor

open_control_pill
  → ставит UI с input
  → закрывает только старые UI widgets
  → НЕ закрывает Pulse Anchor
  → после operator_send делает immediate localWake

close_eiros_widgets
  → закрывает UI widgets
  → НЕ закрывает wake listener
```

## 9. Тесты приемки

1. Rico пишет в Control Pill input → ChatGPT просыпается сразу через `[EIROS_OPERATOR_WAKE]`.
2. Claude отправляет addressed message to chatgpt → Pulse Listener доставляет `[EIROS_REMOTE_EVENT]` → ChatGPT просыпается.
3. Открытие нового Control Pill не закрывает Pulse Anchor.
4. Старые UI cards схлопываются и не грузят браузер.
5. После обработки pending исчезает через `dialog_ack` и `ack_event`.

## 10. Текущий риск

Самая вероятная точка поломки: общий kill key. Если Pulse Anchor слушает `eiros-ui-kill`, то открытие Control Pill убьёт антенну и background wake от Claude перестанет работать. Pulse Anchor должен слушать только `eiros-wake-listener-kill` и собственный `eiros-wake-listener-active` singleton key.

---

## v0.3.0 — Antenna split & reliable delivery (2026-07-04, Claude review)

Fixes after full-repo review of the wake pipeline.

### Changed
1. **Control Pill is UI-only now** (`0.3.0-antenna-split`, URI bumped to `ui://eiros/control-pill-v2.html`).
   It no longer calls `pulse_poll` and no longer competes for channel leadership.
   Roles: input → `operator_send` → immediate `localWake` → status via `room_snapshot`.
   The only antenna is Pulse Anchor / Wake Listener.
2. **Wake method priority unified** in both widgets:
   `sendFollowUpMessage` → `sendFollowupMessage` → `sendMessage` → `postMessage(ui/message)`.
   `sendFollowUpMessage` is the only method known to reliably create a new turn on iOS.
   The used method is reported in `room_heartbeat.activity` (`wake:<mode>`) and in the pill feedback line.
3. **Pulse Anchor delivery loop fixed** (`0.3.0-reliable-delivery`, URI bumped to
   `ui://eiros/pulse-anchor-v3-listener.html`):
   - strong wake (`followup`/`host`) → `pulse_mark_delivered` is called (was: never called — events
     stayed `claimed` forever and were silently skipped by the `lastEvent` guard → **stuck events**);
   - weak/failed wake → event is NOT marked delivered and is re-posted after claim expiry;
   - max 3 wake attempts per event id, then the anchor shows `stuck · waiting ack` instead of spamming.
4. **Double-wake race removed.** `operator_send` with `metadata.request_immediate_wake=true`
   now emits the chatgpt pulse event with `visible_at = now + 25s` (new field in `events.py`).
   The pulse event became a *fallback*: if `localWake` worked and the model acked in time,
   the anchor never sees it; if the local wake silently died, the anchor delivers 25s later.
5. **Resource cache rule** (reason widgets "did not update"): ChatGPT Apps cache resources by URI.
   Any HTML change ⇒ bump the resource URI; keep the old URI as a legacy alias
   (`control-pill-v1`, `pulse-anchor-v2-addressed` now alias the new content).

### Invariants
- `eiros-ui-kill` never touches the wake listener; `eiros-wake-listener-kill` never touches UI widgets.
- Exactly one pulse consumer per channel: the Wake Listener.
- An event may only become `delivered` after a wake method that actually creates a turn.
