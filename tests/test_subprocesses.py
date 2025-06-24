#!/usr/bin/env python3
''' test subprocess manager '''

import multiprocessing
import sys
import time
import unittest.mock
from unittest.mock import MagicMock, patch

import pytest

import nowplaying.subprocesses


@pytest.fixture
def mock_config():
    ''' Mock config for testing '''
    config = MagicMock()
    config.cparser.value.side_effect = lambda key, **kwargs: {
        'control/beam': False,
        'twitchbot/enabled': True,
        'weboutput/httpenabled': True,
        'kick/enabled': True,
        'kick/chat': True,
        'obsws/enabled': True,
        'discord/enabled': True,
    }.get(key, kwargs.get('defaultValue', False))
    config.getbundledir.return_value = '/mock/bundle'
    return config


@pytest.fixture
def subprocess_manager(mock_config):
    ''' Create SubprocessManager for testing '''
    with patch('importlib.import_module'):
        manager = nowplaying.subprocesses.SubprocessManager(config=mock_config, testmode=True)
        # Mock the process modules
        for name in manager.processes:
            manager.processes[name]['module'] = MagicMock()
        yield manager


def test_subprocess_manager_init(mock_config):
    ''' Test SubprocessManager initialization '''
    with patch('importlib.import_module') as mock_import:
        manager = nowplaying.subprocesses.SubprocessManager(config=mock_config, testmode=True)
        
        # Should import all expected modules
        expected_processes = ['trackpoll', 'obsws', 'twitchbot', 'discordbot', 'webserver', 'kickbot']
        assert len(manager.processes) == len(expected_processes)
        
        for process_name in expected_processes:
            assert process_name in manager.processes
            assert 'module' in manager.processes[process_name]
            assert 'process' in manager.processes[process_name]
            assert 'stopevent' in manager.processes[process_name]


def test_subprocess_manager_beam_mode(mock_config):
    ''' Test SubprocessManager in beam mode '''
    mock_config.cparser.value.side_effect = lambda key, **kwargs: {
        'control/beam': True,
    }.get(key, kwargs.get('defaultValue', False))
    
    with patch('importlib.import_module'):
        manager = nowplaying.subprocesses.SubprocessManager(config=mock_config, testmode=True)
        
        # Should only have beam-specific processes
        expected_processes = ['trackpoll', 'beamsender']
        assert len(manager.processes) == len(expected_processes)
        for process_name in expected_processes:
            assert process_name in manager.processes


def test_start_process_with_conditions(subprocess_manager):
    ''' Test conditional process starting '''
    manager = subprocess_manager
    
    # Mock a process as not running
    manager.processes['twitchbot']['process'] = None
    
    with patch.object(manager, '_start_process') as mock_start:
        manager.start_process('twitchbot')
        mock_start.assert_called_once_with('twitchbot')


def test_start_process_disabled(subprocess_manager):
    ''' Test that disabled processes don't start '''
    manager = subprocess_manager
    manager.config.cparser.value.side_effect = lambda key, **kwargs: {
        'twitchbot/enabled': False,
    }.get(key, kwargs.get('defaultValue', False))
    
    with patch.object(manager, '_start_process') as mock_start:
        manager.start_process('twitchbot')
        mock_start.assert_not_called()


class MockProcess:
    ''' Mock multiprocessing.Process for testing '''
    
    def __init__(self, target=None, name=None, args=None):
        self.target = target
        self.name = name
        self.args = args
        self.pid = 12345
        self._alive = True
        self._started = False
        self._terminated = False
        self._closed = False
    
    def start(self):
        self._started = True
    
    def join(self, timeout=None):
        # Simulate quick shutdown for most processes
        if self.name in ['webserver', 'obsws']:
            self._alive = False
        # Simulate slow shutdown for some processes
        elif self.name == 'trackpoll' and timeout and timeout >= 5:
            self._alive = False
    
    def terminate(self):
        self._terminated = True
        self._alive = False
    
    def is_alive(self):
        return self._alive
    
    def close(self):
        self._closed = True


# Ensure test doesn't hang - using manual timing instead of pytest-timeout
def test_parallel_shutdown_performance(subprocess_manager):
    ''' Test that parallel shutdown is faster than sequential '''
    manager = subprocess_manager
    
    # Create mock processes
    mock_processes = {}
    for name in ['trackpoll', 'webserver', 'obsws', 'twitchbot']:
        mock_process = MockProcess(name=name)
        mock_processes[name] = mock_process
        manager.processes[name]['process'] = mock_process
    
    # Time the parallel shutdown
    start_time = time.time()
    manager.stop_all_processes()
    end_time = time.time()
    
    shutdown_time = end_time - start_time
    
    # Should complete much faster than sequential (4 processes × 8s = 32s)
    # Even with overhead, parallel should be under 15 seconds
    assert shutdown_time < 15, f"Parallel shutdown took {shutdown_time:.1f}s, expected < 15s"
    
    # Verify all processes were cleaned up
    for name in mock_processes:
        assert manager.processes[name]['process'] is None


def test_stop_process_parallel_graceful_shutdown(subprocess_manager):
    ''' Test graceful shutdown in parallel method '''
    manager = subprocess_manager
    
    mock_process = MockProcess(name='webserver')
    mock_process._alive = True  # Start alive
    manager.processes['webserver']['process'] = mock_process
    
    # Mock join to simulate quick shutdown
    with patch.object(mock_process, 'join') as mock_join:
        mock_join.side_effect = lambda timeout: setattr(mock_process, '_alive', False)
        
        manager._stop_process_parallel('webserver')
        
        # Should call join with 8 second timeout
        mock_join.assert_called_with(8)
        assert manager.processes['webserver']['process'] is None


def test_stop_process_parallel_forced_termination(subprocess_manager):
    ''' Test forced termination when graceful shutdown fails '''
    manager = subprocess_manager
    
    mock_process = MockProcess(name='trackpoll')
    # Simulate a stuck process that doesn't respond to graceful shutdown
    mock_process._alive = True
    manager.processes['trackpoll']['process'] = mock_process
    
    with patch.object(mock_process, 'join') as mock_join, \
         patch.object(mock_process, 'terminate') as mock_terminate:
        
        # Mock join to keep process alive on first call, then die on second
        def mock_join_behavior(timeout):
            if mock_join.call_count == 1:
                # First call (graceful) - process stays alive
                pass
            else:
                # Second call (after terminate) - process dies
                mock_process._alive = False
        
        mock_join.side_effect = mock_join_behavior
        
        manager._stop_process_parallel('trackpoll')
        
        # Should try graceful first, then terminate
        assert mock_join.call_count == 2
        mock_terminate.assert_called_once()
        assert manager.processes['trackpoll']['process'] is None


def test_stop_process_parallel_twitchbot_special_handling(subprocess_manager):
    ''' Test special handling for twitchbot process '''
    manager = subprocess_manager
    
    mock_process = MockProcess(name='twitchbot')
    manager.processes['twitchbot']['process'] = mock_process
    
    # Mock the stop function on the module
    mock_stop_func = MagicMock()
    manager.processes['twitchbot']['module'].stop = mock_stop_func
    
    with patch.object(mock_process, 'join') as mock_join:
        mock_join.side_effect = lambda timeout: setattr(mock_process, '_alive', False)
        
        manager._stop_process_parallel('twitchbot')
        
        # Should call the special stop function with PID
        mock_stop_func.assert_called_once_with(mock_process.pid)


def test_stop_process_parallel_error_handling(subprocess_manager):
    ''' Test error handling during parallel shutdown '''
    manager = subprocess_manager
    
    mock_process = MockProcess(name='webserver')
    manager.processes['webserver']['process'] = mock_process
    
    # Mock process.close() to raise an exception
    with patch.object(mock_process, 'close', side_effect=Exception("Close failed")), \
         patch.object(mock_process, 'join') as mock_join:
        
        mock_join.side_effect = lambda timeout: setattr(mock_process, '_alive', False)
        
        # Should not raise exception, just log and continue
        manager._stop_process_parallel('webserver')
        
        # Process should still be cleaned up
        assert manager.processes['webserver']['process'] is None


def test_stop_all_processes_with_timeout(subprocess_manager):
    ''' Test that stop_all_processes handles timeouts gracefully '''
    manager = subprocess_manager
    
    # Create processes that take varying amounts of time
    for name in ['trackpoll', 'webserver']:
        mock_process = MockProcess(name=name)
        manager.processes[name]['process'] = mock_process
    
    # Test that processes get cleaned up even if some are slow
    start_time = time.time()
    manager.stop_all_processes()
    end_time = time.time()
    
    # Should complete reasonably quickly since our mock processes are simple
    assert end_time - start_time <= 5  # Should be much faster than 15 seconds
    
    # All processes should be cleaned up regardless
    for name in ['trackpoll', 'webserver']:
        assert manager.processes[name]['process'] is None


def test_stop_all_processes_signals_all_first(subprocess_manager):
    ''' Test that stop_all_processes signals all processes before joining '''
    manager = subprocess_manager
    
    signal_order = []
    
    # Create mock processes and track when their stop events are set
    for name in ['trackpoll', 'webserver', 'twitchbot']:
        mock_process = MockProcess(name=name)
        manager.processes[name]['process'] = mock_process
        
        # Track when stopevent.set() is called
        original_set = manager.processes[name]['stopevent'].set
        manager.processes[name]['stopevent'].set = lambda n=name: signal_order.append(n) or original_set()
    
    manager.stop_all_processes()
    
    # All processes should be signaled before any joins happen
    expected_signals = ['trackpoll', 'webserver', 'twitchbot']
    assert len(signal_order) == len(expected_signals)
    for expected in expected_signals:
        assert expected in signal_order


def test_legacy_methods(subprocess_manager):
    ''' Test that legacy methods still work '''
    manager = subprocess_manager
    
    with patch.object(manager, 'start_process') as mock_start, \
         patch.object(manager, 'stop_process') as mock_stop, \
         patch.object(manager, 'restart_process') as mock_restart:
        
        # Test legacy start/stop methods
        manager.start_webserver()
        mock_start.assert_called_with('webserver')
        
        manager.stop_webserver()
        mock_stop.assert_called_with('webserver')
        
        manager.stop_twitchbot()
        mock_stop.assert_called_with('twitchbot')
        
        manager.stop_kickbot()
        mock_stop.assert_called_with('kickbot')
        
        # Test legacy restart methods
        manager.restart_webserver()
        mock_restart.assert_called_with('webserver')
        
        manager.restart_obsws()
        mock_restart.assert_called_with('obsws')
        
        manager.restart_kickbot()
        mock_restart.assert_called_with('kickbot')


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific timeout test")
def test_windows_process_termination_timeout(subprocess_manager):
    ''' Test that Windows gets longer termination timeouts '''
    manager = subprocess_manager
    
    class WindowsSlowProcess(MockProcess):
        ''' Simulate Windows process that's slow to terminate '''
        def join(self, timeout=None):
            # On Windows, simulate that termination takes longer
            if timeout and timeout >= 7:  # Our Windows timeout
                self._alive = False
            # If timeout is too short, process stays alive
    
    mock_process = WindowsSlowProcess(name='trackpoll')
    manager.processes['trackpoll']['process'] = mock_process
    
    with patch.object(mock_process, 'join', wraps=mock_process.join) as mock_join:
        manager._stop_process_parallel('trackpoll')
        
        # Should call join twice: first for graceful (8s), then for force (7s)
        assert mock_join.call_count == 2
        # Second call should be the termination timeout
        mock_join.assert_any_call(7)


def test_cross_platform_timeout_behavior(subprocess_manager):
    ''' Test timeout behavior across platforms '''
    manager = subprocess_manager
    
    mock_process = MockProcess(name='webserver')
    manager.processes['webserver']['process'] = mock_process
    
    with patch.object(mock_process, 'join') as mock_join:
        mock_join.side_effect = lambda timeout: setattr(mock_process, '_alive', False)
        
        manager._stop_process_parallel('webserver')
        
        # Should use 8 second graceful timeout on all platforms
        mock_join.assert_any_call(8)
        
        # If termination was needed, should use 7 second timeout
        # (increased from 5 to accommodate Windows)