import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from modules.daikin.controller import DaikinController, DaikinDevice


class DaikinTimeoutTests(unittest.TestCase):
    def test_stalled_command_releases_lock_and_next_request_succeeds(self):
        controller = DaikinController([DaikinDevice('test', 'Test', 'AA:BB')])
        controller._command_timeout = 0.02
        connection = SimpleNamespace(client=None, _connect=AsyncMock())
        madoka = SimpleNamespace(connection=connection, stop=AsyncMock())
        process = SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0))
        lib = {'Controller': Mock(return_value=madoka),
               'BleakScanner': SimpleNamespace(find_device_by_address=AsyncMock(return_value=object())),
               'BleakClient': Mock(return_value=SimpleNamespace(disconnect=AsyncMock())),
               'connection_module': SimpleNamespace()}

        async def stalled(*args):
            await asyncio.Event().wait()

        async def succeeds(*args):
            return {'ok': True, 'setpoint': 23}

        try:
            with patch('modules.daikin.controller._load_pymadoka', return_value=lib), patch(
                    'modules.daikin.controller.asyncio.create_subprocess_exec', AsyncMock(return_value=process)):
                result = controller._run(controller.devices[0], stalled, 'setpoint')
                self.assertFalse(result['ok'])
                self.assertIn('timed out', result['error'])
                self.assertFalse(controller._ble_lock.locked())
                result = controller._run(controller.devices[0], succeeds, 'status')
                self.assertTrue(result['ok'])
                self.assertEqual(madoka.stop.await_count, 2)
        finally:
            controller._ble_loop.call_soon_threadsafe(controller._ble_loop.stop)
            controller._ble_loop_thread.join(timeout=1)
            controller._ble_loop.close()

    def test_background_poll_yields_to_waiting_user_request(self):
        controller = DaikinController([])
        with patch('modules.daikin.controller.threading.current_thread',
                   return_value=SimpleNamespace(name='daikin-poller')):
            controller._waiting_requests = 1
            self.assertFalse(controller._acquire_ble_lock())
            controller._waiting_requests = 0
            self.assertTrue(controller._acquire_ble_lock())
            controller._ble_lock.release()

    def test_loop_start_failure_releases_lock(self):
        controller = DaikinController([DaikinDevice('test', 'Test', 'AA:BB')])
        with patch('modules.daikin.controller._load_pymadoka', return_value={}), patch.object(
                controller, '_ensure_ble_loop', side_effect=RuntimeError('loop failed')):
            self.assertFalse(controller.get_status('test')['ok'])
        self.assertFalse(controller._ble_lock.locked())


if __name__ == '__main__':
    unittest.main()
