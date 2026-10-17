"""The suite's log line format, for pytest's captured logs (report.html) and
the run log file (suite.log):

    11:58:01.34 2026-10-17 [DEBUG   ] claude_cli.py:60 run_claude() - run: claude mcp list

Time is local, to hundredths of a second, then the date. Log lines must not
hold a secret: callers log redacted argv and statuses only, never raw CLI
output (the entrypoint still scans report.html and suite.log for the key)."""

import logging
import time

LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(filename)s:%(lineno)d %(funcName)s() - %(message)s"
LOG_TIME_FORMAT = "%H:%M:%S"
LOG_DATE_FORMAT = "%Y-%m-%d"
CENTISECONDS_PER_SECOND = 100
MILLISECONDS_PER_CENTISECOND = 10
LOGGING_PLUGIN_NAME = "logging-plugin"  # pytest's LoggingPlugin
LOGGING_PLUGIN_HANDLERS = ("caplog_handler", "report_handler", "log_file_handler", "log_cli_handler")


class SuiteFormatter(logging.Formatter):
    def formatTime(self, record, datefmt):  # noqa: N802 (logging API name); datefmt is unused
        local = time.localtime(record.created)
        centiseconds = int(record.msecs) // MILLISECONDS_PER_CENTISECOND
        return "%s.%02d %s" % (
            time.strftime(LOG_TIME_FORMAT, local), centiseconds % CENTISECONDS_PER_SECOND,
            time.strftime(LOG_DATE_FORMAT, local),
        )


def install_on_pytest(*, config):
    """Give every handler of pytest's logging plugin the suite format. Call
    from pytest_sessionstart: in pytest_configure the plugin is not there yet."""
    plugin = config.pluginmanager.get_plugin(LOGGING_PLUGIN_NAME)
    assert plugin is not None, "pytest logging plugin not registered"
    formatter = SuiteFormatter(fmt=LOG_FORMAT, datefmt=None)
    for name in LOGGING_PLUGIN_HANDLERS:
        if hasattr(plugin, name):
            getattr(plugin, name).setFormatter(formatter)
