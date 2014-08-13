from flask.ext.script import Command, Option
from gunicorn.app.base import Application as GunicornApplication
from gunicorn.config import Config as GunicornConfig
from splice.utils import environment_manager_create


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
                app = environment_manager_create()
                return app

            def load_config(self):
                # Overriding to prevent Gunicorn from reading
                # the command-line arguments
                self.cfg = GunicornConfig(self.usage, prog=self.prog)
                cfg = self.init()
                if cfg and cfg is not None:
                    for k, v in cfg.items():
                        self.cfg.set(k.lower(), v)

        GunicornServer().run()

class SeedDataCommand(Command):
    """
    Insert seed data in an empty database
    """

    def load_locales(self, filepath):
        data = None
        with open(filepath, 'r') as infile:
            data = infile.readlines()
        return data

    def load_countries(self, filepath):
        data = None
        import csv
        with open(filepath, 'rb') as f:
            reader = csv.DictReader(f)
            data = [(d['ISO 3166-1 2 Letter Code'], d['Common Name']) for d in reader]
        return data

    def run(self, **kwargs):
        from splice.environment import Environment
        from splice.models import Country, Locale
        env = Environment.instance()

        locale_data = self.load_locales(env.config.LOCALE_FIXTURE_PATH)
        for locale_str in locale_data:
            locale = Locale(name=locale_str)
            env.db.session.add(locale)
        env.db.session.add(Locale(name="ERROR"))

        country_data = self.load_countries(env.config.COUNTRY_FIXTURE_PATH)
        for code, name in country_data:
            if code:
                env.db.session.add(Country(code=code, name=name))

        env.db.session.add(Country(code="ERROR", name="GeoIP Lookup Error"))

        env.db.session.commit()