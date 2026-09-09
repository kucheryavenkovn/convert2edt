#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1C Host Bridge как Windows-сервис (pywin32).

Установка (host/install-service.ps1 делает то же самое):
  python bridge_service.py --setup <config-path>
  sc.exe create 1CHostBridge binPath= ... --config <path>
"""
import sys

import servicemanager
import win32serviceutil
import win32service
import win32event

import bridge


class BridgeService(win32serviceutil.ServiceFramework):
    _svc_name_ = "1CHostBridge"
    _svc_display_name_ = "1C Host Bridge (gitsync converter)"
    _svc_description_ = ("Allowlisted запуск локального 1cv8 DESIGNER/CREATEINFOBASE "
                         "по запросу из Docker-конвертера. См. docs/SPEC.md.")
    _svc_restart_on_fail_ = True

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.httpd = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.httpd:
            try:
                self.httpd.shutdown()
            except Exception:
                pass

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED, (self._svc_name_, ""))
        config_path = None
        # binPath: bridge_service.py --config <path>
        args = sys.argv[1:]
        if "--config" in args:
            config_path = args[args.index("--config") + 1]
        try:
            cfg = bridge.load_config(config_path)
            bridge.setup_logging(cfg)
            runner = bridge.Runner(cfg)
            host, port = cfg["listen"].rsplit(":", 1)
            import os
            os.makedirs(cfg["bridgeRoot"], exist_ok=True)
            from http.server import ThreadingHTTPServer
            self.httpd = ThreadingHTTPServer((host, int(port)), bridge.make_handler(cfg, runner))
            self.httpd.serve_forever(poll_interval=2)
        except Exception as exc:  # сервис не должен молча умирать
            servicemanager.LogErrorMsg("1CHostBridge failed: %r" % (exc,))
            raise


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(BridgeService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(BridgeService)
