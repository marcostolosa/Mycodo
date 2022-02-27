# coding=utf-8
import threading

from flask_babel import lazy_gettext

from mycodo.config import SQL_DATABASE_MYCODO
from mycodo.config_translations import TRANSLATIONS
from mycodo.databases.models import Actions
from mycodo.databases.models import Method
from mycodo.databases.models import PID
from mycodo.databases.utils import session_scope
from mycodo.function_actions.base_function_action import AbstractFunctionAction
from mycodo.utils.database import db_retrieve_table_daemon

MYCODO_DB_PATH = 'sqlite:///' + SQL_DATABASE_MYCODO

FUNCTION_ACTION_INFORMATION = {
    'name_unique': 'method_pid',
    'name': '{}: {}'.format(
        TRANSLATIONS['pid']['title'], lazy_gettext('Set Method')),
    'library': None,
    'manufacturer': 'Mycodo',

    'url_manufacturer': None,
    'url_datasheet': None,
    'url_product_purchase': None,
    'url_additional': None,

    'message': lazy_gettext('Select a method to set the PID to use.'),

    'usage': 'Executing <strong>self.run_action("{ACTION_ID}")</strong> will pause the selected PID Controller. '
             'Executing <strong>self.run_action("{ACTION_ID}", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "method_id": "fe8b8f41-131b-448d-ba7b-00a044d24075"})</strong> will set the PID Controller with the specified ID (e.g. 959019d1-c1fa-41fe-a554-7be3366a9c5b) to the method with the specified ID (e.g. "fe8b8f41-131b-448d-ba7b-00a044d24075").',

    'dependencies_module': [],

    'custom_options': [
        {
            'id': 'controller',
            'type': 'select_device',
            'default_value': '',
            'options_select': [
                'PID'
            ],
            'name': lazy_gettext('Controller'),
            'phrase': 'Select the PID Controller to apply the method'
        },
        {
            'id': 'method',
            'type': 'select_device',
            'default_value': '',
            'options_select': [
                'Method'
            ],
            'name': lazy_gettext('Method'),
            'phrase': 'Select the Method to apply to the PID'
        }
    ]
}


class ActionModule(AbstractFunctionAction):
    """
    Function Action: PID Set Method
    """
    def __init__(self, action_dev, testing=False):
        super(ActionModule, self).__init__(action_dev, testing=testing, name=__name__)

        self.controller_id = None
        self.method_id = None

        action = db_retrieve_table_daemon(
            Actions, unique_id=self.unique_id)
        self.setup_custom_options(
            FUNCTION_ACTION_INFORMATION['custom_options'], action)

        if not testing:
            self.setup_action()

    def setup_action(self):
        self.action_setup = True

    def run_action(self, message, dict_vars):
        try:
            controller_id = dict_vars["value"]["pid_id"]
        except:
            controller_id = self.controller_id

        try:
            method_id = dict_vars["value"]["method_id"]
        except:
            method_id = self.method_id

        pid = db_retrieve_table_daemon(
            PID, unique_id=controller_id, entry='first')

        if not pid:
            msg = "PID Controller with ID {} doesn't exist.".format(controller_id)
            message += msg
            self.logger.error(msg)
            return message

        method = db_retrieve_table_daemon(
            Method, unique_id=method_id, entry='first')

        if not method:
            msg = "Method with ID {} doesn't exist.".format(method_id)
            message += msg
            self.logger.error(msg)
            return message

        message += " Set Method of PID {unique_id} ({id}, {name}).".format(
            unique_id=controller_id,
            id=pid.id,
            name=pid.name)

        if pid.is_activated:
            method_pid = threading.Thread(
                target=self.control.pid_set,
                args=(controller_id,
                      'method',
                      method_id,))
            method_pid.start()
        else:
            with session_scope(MYCODO_DB_PATH) as new_session:
                mod_pid = new_session.query(PID).filter(
                    PID.unique_id == controller_id).first()
                mod_pid.method_id = method_id
                new_session.commit()

        return message

    def is_setup(self):
        return self.action_setup