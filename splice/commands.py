import os
import multiprocessing
import logging
import sys
import json
import calendar
from datetime import datetime
from operator import itemgetter
from flask.ext.script import Command, Option, Manager
from flask.ext.script.commands import InvalidCommand
from gunicorn.app.base import Application as GunicornApplication
from gunicorn.config import Config as GunicornConfig

command_logger_set = False


def setup_command_logger(loglevel=None):
    global command_logger_set
    if not command_logger_set:
        loglevel = loglevel or logging.INFO
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(loglevel)

        try:
            from colorlog import ColoredFormatter
            fmt = ColoredFormatter("%(log_color)s%(message)s",
                                   log_colors={
                                       "DEBUG": "cyan",
                                       "INFO": "green",
                                       "WARNING": "yellow",
                                       "ERROR": "red",
                                       "CRITICAL": "bold_red"})
        except ImportError:
            # fall back to non-colored output
            fmt = logging.Formatter("%(message)s")

        handler.setFormatter(fmt)

        logger = logging.getLogger("command")
        logger.addHandler(handler)
        logger.setLevel(loglevel)
        command_logger_set = True
    else:
        logger = logging.getLogger("command")

    return logger


class GunicornServerCommand(Command):
    """
    Run the splice Server using gunicorn
    """
    def __init__(self, host='127.0.0.1', port=5000, workers=1,
                 access_logfile='-', max_requests=0, debug=True):
        self.options = {
            "host": host,
            "port": port,
            "workers": workers,
            "access_logfile": access_logfile,
            "max_requests": max_requests,
            "debug": debug,
        }

    def get_options(self):
        options = (
            Option('-H', '--host',
                   dest='host',
                   type=str,
                   default=self.options['host'],
                   help="hostname to bind server to"),
            Option('-p', '--port',
                   dest='port',
                   type=int,
                   default=self.options['port'],
                   help="port to bind server to"),
            Option('-w', '--workers',
                   dest='workers',
                   type=int,
                   default=self.options['workers'],
                   help="set the number of workers"),
            Option('--access-logfile',
                   dest='access_logfile',
                   type=str,
                   default=self.options['access_logfile'],
                   help="set the access log output location"),
            Option('--max-requests',
                   dest='max_requests',
                   type=int,
                   default=self.options['max_requests'],
                   help="set the maximum number of requests " +
                        "to serve before reloading"),
            Option('--no-debug',
                   dest='debug',
                   action='store_false',
                   default=self.options['debug'],
                   help="turn off debug mode"),
        )
        return options

    def run(self, **kwargs):
        self.options.update(kwargs)
        if not kwargs.get('debug'):
            self.options['workers'] = multiprocessing.cpu_count() * 2 + 1

        options = self.options

        class GunicornServer(GunicornApplication):
            def init(self, **kwargs):
                config = {
                    'bind': '{0}:{1}'.format(
                        options['host'],
                        options['port']
                    ),
                    'workers': options['workers'],
                    'worker_class': 'gevent',
                    'accesslog': options['access_logfile'],
                    'max_requests': options['max_requests'],
                }
                return config

            def load(self):
                # Step needed to get around flask's import time side-effects
                from splice.environment import Environment
                env = Environment.instance()
                return env.application

            def load_config(self):
                # Overriding to prevent Gunicorn from reading
                # the command-line arguments
                self.cfg = GunicornConfig(self.usage, prog=self.prog)
                cfg = self.init()
                if cfg and cfg is not None:
                    for k, v in cfg.items():
                        self.cfg.set(k.lower(), v)

        GunicornServer().run()

DataCommand = Manager(usage="database import/export utility")


ListCommand = Manager(usage="list http endpoints enabled")


@ListCommand.command
def urls():
    """
    Return available endpoints
    """
    logger = setup_command_logger()

    endpoints = []
    from flask import current_app
    for rule in current_app.url_map.iter_rules():
        try:
            endpoints.append((
                rule.rule,
                sorted(list(rule.methods)),
            ))
        except Exception, e:
            logger.error(e)

    endpoints = sorted(endpoints, key=itemgetter(0))
    for url, methods in endpoints:
        logger.info("{0} {1}".format(
            url,
            json.dumps(methods),
        ))


@DataCommand.option("-v", "--verbose", action="store_true", dest="verbose", help="turns on verbose mode", default=False, required=False)
@DataCommand.option("-p", "--preserve-format", action="store_true", dest="old_format", help="To keep data in the non-country aware format", required=False)
@DataCommand.option("-c", "--console", action="store_true", dest="console_out", help="Enable console output", required=False)
@DataCommand.option("-o", "--out_path", type=str, help="To dump to a file, provide a path/filename", required=False)
@DataCommand.option("in_file", type=str, help="Path to directoryLinks.json file")
@DataCommand.option("country_code", type=str, help="ISO3166 country code for the file")
def load_links(in_file, country_code, out_path, console_out, verbose, old_format, *args, **kwargs):
    """
    Load a set of links in the data warehouse
    """
    if verbose:
        logger = setup_command_logger(logging.DEBUG)
    else:
        logger = setup_command_logger(logging.INFO)

    rawdata = None
    with open(in_file, 'r') as f:
        rawdata = json.load(f)

    from splice.ingest import ingest_links, IngestError

    try:
        locale = rawdata.keys()[0]
        country_locale_str = "/".join([country_code, locale])

        new_data = ingest_links({country_locale_str: rawdata[locale]})

        if old_format:
            new_data = new_data[new_data.keys()[0]]

        if console_out:
            print json.dumps(new_data, sort_keys=True, indent=2)

        if out_path:
            directory, _ = os.path.split(out_path)
            if not os.path.exists(directory):
                os.makedirs(directory)

            with open(out_path, "w") as f:
                json.dump(new_data, f, sort_keys=True, indent=2)
                logger.info("wrote {0}".format(out_path))

    except IngestError, e:
        raise InvalidCommand(e.message)
    except:
        import traceback
        traceback.print_exc()


@DataCommand.option("-v", "--verbose", action="store_true", dest="verbose", help="turns on verbose mode", default=False, required=False)
@DataCommand.option("-d", "--deploy", action="store_true", dest="deploy_flag", help="Deploy to S3", required=False)
@DataCommand.option("-c", "--console", action="store_true", dest="console_out", help="Enable console output", required=False)
@DataCommand.option("-o", "--out_path", type=str, help="To dump to a file, provide a path/filename", required=False)
@DataCommand.option("in_file", type=str, help="Path to tiles.json file")
def ingest_tiles(in_file, out_path, console_out, deploy_flag, verbose, *args, **kwargs):
    """
    Load a set of links for all country/locale combinations into data warehouse and optionally deploy
    """
    if verbose:
        logger = setup_command_logger(logging.DEBUG)
    else:
        logger = setup_command_logger(logging.INFO)

    rawdata = None
    with open(in_file, 'r') as f:
        rawdata = json.load(f)

    from splice.ingest import ingest_links, deploy, IngestError

    try:
        new_data = ingest_links(rawdata)

        if console_out:
            print json.dumps(new_data, sort_keys=True, indent=2)

        if out_path:
            directory, _ = os.path.split(out_path)
            if not os.path.exists(directory):
                os.makedirs(directory)

            with open(out_path, "w") as f:
                json.dump(new_data, f, sort_keys=True, indent=2)
                logger.info("wrote {0}".format(out_path))

        if deploy_flag:
            deploy(new_data)
    except IngestError, e:
        raise InvalidCommand(e.message)
    except:
        import traceback
        traceback.print_exc()


RedshiftCommand = Manager(usage="Redshift utility commands")


@RedshiftCommand.option("out_path", type=str, help="Path to output new migration file")
def new_migration(out_path, *args, **kwargs):
    """
    Create an empty migration file
    """
    logger = setup_command_logger(logging.INFO)

    utc_seconds = calendar.timegm(datetime.utcnow().timetuple())
    file_path = os.path.join(out_path, "{0}.sql".format(utc_seconds))
    open(file_path, "a").close()
    logger.info("wrote {0}".format(file_path))
