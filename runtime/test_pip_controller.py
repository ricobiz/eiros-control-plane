from pathlib import Path
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PipControllerBehaviorTests(unittest.TestCase):
    def test_host_pip_is_primary_even_when_video_is_not_ready(self) -> None:
        script = textwrap.dedent(
            """
            const { activateKeepalivePip } = require('./runtime/pip_controller.js');

            (async () => {
              const calls = [];
              const result = await activateKeepalivePip({
                requestHostPip: async () => {
                  calls.push('host');
                  return true;
                },
                isVideoReady: () => false,
                requestNativeVideoPip: async () => {
                  calls.push('native');
                  return true;
                },
              });

              if (!result.ok || result.mode !== 'host-pip') {
                throw new Error('expected host-pip success: ' + JSON.stringify(result));
              }
              if (calls.join(',') !== 'host') {
                throw new Error('native video PiP must not run after host success: ' + calls.join(','));
              }
            })().catch((error) => {
              console.error(error.stack || error);
              process.exit(1);
            });
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
