import errno
import json
import logging
import os
from dataclasses import dataclass, field

import jpy
import jpyutil

from .exceptions import MessageNotHandledError, MessageObservedError
from .rule import Rule

DEFAULT_JAR = "jars/drools-yaml-rules-durable-rest-1.0.0-SNAPSHOT-runner.jar"
logger = logging.getLogger(__name__)


@dataclass
class Ruleset:
    name: str
    serialized_ruleset: str
    _rules: dict = field(init=False, repr=False, default_factory=dict)

    def add_rule(self, rule: Rule) -> None:
        self._rules[rule.name] = rule

    def create_session(self) -> int:
        self._jpy_instance = self._make_jpy_instance()
        self._session_id = self._api.createRuleset(
            self.name, self.serialized_ruleset
        )
        return self._session_id

    def assert_event(self, serialized_fact: str):
        return self._process_response(
            self._api.assertEvent(self._session_id, serialized_fact),
            serialized_fact,
        )

    def assert_fact(self, serialized_fact):
        return self._process_response(
            self._api.assertFact(self.session_id, serialized_fact),
            serialized_fact,
        )

    def retract_fact(self, session_id, serialized_fact):
        return self._process_response(
            self._api.retractFact(session_id, serialized_fact), serialized_fact
        )

    def get_facts(self):
        return self._api.getFacts(self.session_id)

    def _start_action_for_state(self):
        resp = self._api.advanceState()
        if resp is None:
            return None
        return ('{ "sid":"0", "id":"sid-0", "$s":1}', resp, 1)

    def _complete_and_start_action(self):
        resp = self._api.advanceState()
        return resp

    def _process_response(self, result: int, serialized_msg: str):
        response = self._start_action_for_state()
        if response:
            _, payload, _ = response
            matches = json.loads(payload)
            for key, value in matches.items():
                if key in self._rules:
                    self._rules[key].callback(value)
        else:
            raise MessageNotHandledError(
                "Message not handled " + serialized_msg
            )

    def _handle_result(self, result, message):
        if result[0] == 1:
            raise MessageNotHandledError(message)
        elif result[0] == 2:
            raise MessageObservedError(message)
        elif result[0] == 3:
            return 0

        return result[1]

    def _make_jpy_instance(self):
        jar_file_path = os.environ.get("DROOLS_JPY_CLASSPATH")
        if jar_file_path is None:
            package_dir = os.path.dirname(os.path.realpath(__file__))
            jar_file_path = os.path.join(package_dir, DEFAULT_JAR)

        if not os.path.exists(jar_file_path):
            raise FileNotFoundError(
                errno.ENOENT, os.strerror(errno.ENOENT), jar_file_path
            )

        jpyutil.init_jvm(jvm_maxmem="512M", jvm_classpath=[jar_file_path])

        JpyDurableRulesEngine_JavaAPI = jpy.get_type(
            "org.drools.yaml.durable.jpy.JpyDurableRulesEngine"
        )
        self._api = JpyDurableRulesEngine_JavaAPI()
