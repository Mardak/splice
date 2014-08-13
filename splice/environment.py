import importlib
from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.migrate import Migrate


class EnvironmentUninitializedError(Exception): pass

class Environment(object):

    @classmethod
    def instance(cls, config=None):
        if hasattr(Environment, "_instance") and config is None:
            return Environment._instance
        elif config is not None:
            return Environment(config)

        raise EnvironmentUninitializedError("Cannot obtain instance if uninitialized")

    def __init__(self, config_filename):
        self.__application = None
        self.__db = None

        self.__config_filename = config_filename

        self.config = self.load_config_obj(config_filename)
        self.init()
        if not hasattr(Environment, "_instance"):
            Environment._instance = self

    def load_config_obj(self, obj_name):
        tokens = obj_name.split(".")
        module_name = ".".join(tokens[:-1])
        class_name = tokens[-1]
        module = importlib.import_module(module_name)
        return getattr(module, class_name)

    @property
    def is_debug(self):
        return self.config.DEBUG

    @property
    def is_test(self):
        return self.config.ENVIRONMENT == "test"

    @property
    def is_development(self):
        return self.config.ENVIRONMENT == "dev"

    @property
    def is_production(self):
        return self.config.ENVIRONMENT == "prod"

    @property
    def application(self):
        if not self.__application:
            raise EnvironmentUninitializedError("Cannot obtain application without initializing environment")
        return self.__application

    @property
    def db(self):
        self.application # raise if application is not initted
        if not self.__db:
            self.__db = SQLAlchemy()
        return self.__db

    def init(self):
        app = Flask('splice')
        app.config.from_object(self.__config_filename)

        if app.config['ENVIRONMENT'] not in app.config['STATIC_ENABLED_ENVS']:
            app.config['STATIC_FOLDER'] = None
        self.__application = app

        self.db.init_app(self.__application)
        Migrate(self.__application, self.db)

        return app