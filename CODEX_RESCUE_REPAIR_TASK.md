# CODEX TASK: repair SSH access on Hetzner server from Rescue Mode

You are operating on the user's own Hetzner VPS. The normal OS SSH access is broken, but Hetzner Rescue Mode SSH on port 22 works.

Target server:

- IPv4: `23.88.52.120`
- Rescue SSH: `root@23.88.52.120:22`
- Repository context: `ricobiz/eiros-control-plane`

Goal:

Restore SSH access to the normal installed Ubuntu system after boot, using the mounted root filesystem from Rescue Mode.

Important safety rules:

1. Do not wipe disks.
2. Do not reinstall the OS.
3. Do not modify application data under `/opt/eiros-control-plane` except reading it if needed.
4. Before changing files on the mounted system, create `.bak-eiros-<timestamp>` backups.
5. Prefer key-based root login. Do not require password login unless the user explicitly asks.
6. Do not reboot until you have shown the planned changes and the user has approved, unless the user explicitly says to proceed autonomously.

Known likely failure:

A systemd `ssh.socket` override was created incorrectly. It likely binds only IPv6 (`[::]`) or otherwise broke IPv4 SSH ingress. Normal OS no longer accepts SSH on 22/443/2222. Rescue Mode still works.

Procedure:

## 1. Inspect disks

Run:

```bash
set -euxo pipefail
lsblk -f
blkid || true
```

Identify the installed Ubuntu root partition. It may be `/dev/sda1`, but verify from filesystem labels, size, and contents. Do not assume blindly.

## 2. Mount root filesystem

Use the detected partition as `ROOT_DEV`. Example:

```bash
ROOT_DEV=/dev/sda1
MNT=/mnt/eiros-target
mkdir -p "$MNT"
mount "$ROOT_DEV" "$MNT"
test -d "$MNT/etc" || { echo "not a root filesystem"; exit 1; }
```

If already mounted, reuse the mountpoint.

## 3. Inspect existing SSH/systemd state

Run:

```bash
set -euxo pipefail
find "$MNT/etc/systemd/system" -maxdepth 4 -iname '*ssh*' -print -exec ls -la {} \; || true
find "$MNT/etc/ssh" -maxdepth 3 -type f -print -exec sed -n '1,220p' {} \; || true
ls -la "$MNT/lib/systemd/system/ssh.service" "$MNT/lib/systemd/system/ssh.socket" || true
readlink -f "$MNT/etc/systemd/system/sockets.target.wants/ssh.socket" || true
readlink -f "$MNT/etc/systemd/system/multi-user.target.wants/ssh.service" || true
```

Show the user what looks broken before editing.

## 4. Back up current SSH configs

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$MNT/root/eiros-rescue-backups-$TS"
cp -a "$MNT/etc/systemd/system/ssh.socket.d" "$MNT/root/eiros-rescue-backups-$TS/ssh.socket.d" 2>/dev/null || true
cp -a "$MNT/etc/ssh" "$MNT/root/eiros-rescue-backups-$TS/ssh" 2>/dev/null || true
cp -a "$MNT/etc/systemd/system/sockets.target.wants" "$MNT/root/eiros-rescue-backups-$TS/sockets.target.wants" 2>/dev/null || true
cp -a "$MNT/etc/systemd/system/multi-user.target.wants" "$MNT/root/eiros-rescue-backups-$TS/multi-user.target.wants" 2>/dev/null || true
```

## 5. Repair SSH socket/service config

Create a conservative systemd socket override that explicitly listens on IPv4 and IPv6 for 22, 443, and 2222:

```bash
mkdir -p "$MNT/etc/systemd/system/ssh.socket.d"
cat > "$MNT/etc/systemd/system/ssh.socket.d/override.conf" <<'EOF'
[Socket]
ListenStream=
ListenStream=0.0.0.0:22
ListenStream=0.0.0.0:443
ListenStream=0.0.0.0:2222
ListenStream=[::]:22
ListenStream=[::]:443
ListenStream=[::]:2222
EOF
```

Create an SSH daemon drop-in:

```bash
mkdir -p "$MNT/etc/ssh/sshd_config.d"
cat > "$MNT/etc/ssh/sshd_config.d/99-eiros-recovery.conf" <<'EOF'
Port 22
Port 443
Port 2222
PubkeyAuthentication yes
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
```

Ensure both socket and service are enabled in the installed system:

```bash
mkdir -p "$MNT/etc/systemd/system/sockets.target.wants" "$MNT/etc/systemd/system/multi-user.target.wants"
if [ -e "$MNT/lib/systemd/system/ssh.socket" ]; then
  ln -sf /lib/systemd/system/ssh.socket "$MNT/etc/systemd/system/sockets.target.wants/ssh.socket"
fi
if [ -e "$MNT/lib/systemd/system/ssh.service" ]; then
  ln -sf /lib/systemd/system/ssh.service "$MNT/etc/systemd/system/multi-user.target.wants/ssh.service"
fi
```

## 6. Ensure root authorized_keys has the key used for Rescue Mode

Determine the public key corresponding to the current SSH session if possible. If not possible, ask the user for the public key only, never the private key.

The target file is:

```bash
install -d -m 700 "$MNT/root/.ssh"
touch "$MNT/root/.ssh/authorized_keys"
chmod 600 "$MNT/root/.ssh/authorized_keys"
```

Append the user's public key if not already present.

## 7. Optional: inspect firewall in mounted OS

Do not flush firewall blindly. Inspect first:

```bash
if [ -f "$MNT/etc/ufw/ufw.conf" ]; then cat "$MNT/etc/ufw/ufw.conf"; fi
find "$MNT/etc" -maxdepth 4 \( -iname '*ufw*' -o -iname '*nft*' -o -iname '*iptables*' \) -print || true
```

If UFW is enabled and blocks 22/443/2222, add allow rules using chroot only if safe. Otherwise, disable UFW only with user approval.

## 8. Show final state

```bash
echo '=== ssh.socket override ==='
cat "$MNT/etc/systemd/system/ssh.socket.d/override.conf"
echo '=== sshd recovery drop-in ==='
cat "$MNT/etc/ssh/sshd_config.d/99-eiros-recovery.conf"
echo '=== authorized_keys tail ==='
tail -5 "$MNT/root/.ssh/authorized_keys" || true
sync
```

## 9. Reboot back into normal OS only after approval

```bash
umount "$MNT" || true
sync
reboot
```

After reboot, test from outside:

```bash
ssh -i <key> -p 22 root@23.88.52.120
ssh -i <key> -p 443 root@23.88.52.120
ssh -i <key> -p 2222 root@23.88.52.120
```

If normal OS still fails, use Hetzner Rescue again and inspect the mounted system logs:

```bash
journalctl --directory="$MNT/var/log/journal" -u ssh.service -u ssh.socket --no-pager -n 200 || true
sed -n '1,220p' "$MNT/var/log/auth.log" 2>/dev/null || true
```
