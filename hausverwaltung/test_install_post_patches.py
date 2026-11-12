"""Post-install entrypoints must resolve without replaying extracted history."""
import importlib
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, call, patch

from hausverwaltung import install


PREFIX = "hausverwaltung.hausverwaltung.patches.post_model_sync."
REQUIRED = (
    "add_heizkosten_period_index",
    "migrate_bankimport_rules_to_builder_config",
    "seed_heizkostenmeldung_vorlage",
    "seed_heizkostenmeldung_vorlage_v2",
    "create_hausverwalter_role",
    "ensure_rent_items",
    "add_accounting_dimension_wohnung",
    "remove_legacy_vorgang_components",
    "normalize_agent_readonly_permissions",
    "migrate_immobilie_accounts_to_child_tables",
    "create_mieter_anrede_vorname_nachname_baustein",
)


class TestPostInstallPatches(unittest.TestCase):
    def test_required_core_initialization_is_preserved_in_order(self):
        self.assertEqual(install._POST_INSTALL_PATCHES, tuple(PREFIX + name for name in REQUIRED))

    def test_entire_list_resolves_to_callable_entrypoints(self):
        for name in install._POST_INSTALL_PATCHES:
            with self.subTest(patch=name):
                module = importlib.import_module(name)
                self.assertTrue(callable(module.execute))
                self.assertIs(install.frappe.get_attr(name + ".execute"), module.execute)

    def test_normal_runner_resolves_executes_and_marks_every_remaining_seed(self):
        # Resolve real modules first. Only their DB-writing execute bodies are
        # replaced; the production resolver and runner are exercised unchanged.
        with ExitStack() as stack:
            executors = []
            for name in install._POST_INSTALL_PATCHES:
                module = importlib.import_module(name)
                executors.append(stack.enter_context(patch.object(module, "execute")))
            log = stack.enter_context(patch.object(install, "_log_install_error"))
            mark = stack.enter_context(patch.object(install, "_mark_patch_executed"))
            stack.enter_context(patch.object(install, "_should_mark_patch_executed", return_value=True))
            commit = stack.enter_context(patch.object(install.frappe.db, "commit"))
            install._run_post_install_patches(reason="after_install")
            for execute in executors:
                execute.assert_called_once_with()
            self.assertEqual(mark.call_args_list, [call(name) for name in install._POST_INSTALL_PATCHES])
            log.assert_not_called()
            commit.assert_called_once_with()

    def test_unexpected_import_failure_remains_visible_and_does_not_hide_other_seeds(self):
        executors = [Mock() for _ in install._POST_INSTALL_PATCHES[1:]]
        with patch.object(install.frappe, "get_attr", side_effect=[ModuleNotFoundError("synthetic missing patch"), *executors]), \
             patch.object(install, "_log_install_error") as log, \
             patch.object(install, "_should_mark_patch_executed", return_value=True), \
             patch.object(install, "_mark_patch_executed") as mark, \
             patch.object(install.frappe.db, "commit") as commit:
            install._run_post_install_patches(reason="after_install")
            log.assert_called_once_with(title="hausverwaltung post-install patch import failed (after_install)",
                                        patch=install._POST_INSTALL_PATCHES[0])
            for execute in executors:
                execute.assert_called_once_with()
            self.assertEqual(mark.call_args_list, [call(name) for name in install._POST_INSTALL_PATCHES[1:]])
            commit.assert_called_once_with()

    def test_unexpected_execution_failure_remains_visible_and_is_not_marked_successful(self):
        executors = [Mock(side_effect=RuntimeError("synthetic patch failure")),
                     *[Mock() for _ in install._POST_INSTALL_PATCHES[1:]]]
        with patch.object(install.frappe, "get_attr", side_effect=executors), \
             patch.object(install, "_log_install_error") as log, \
             patch.object(install, "_should_mark_patch_executed", return_value=True), \
             patch.object(install, "_mark_patch_executed") as mark, \
             patch.object(install.frappe.db, "commit") as commit:
            install._run_post_install_patches(reason="after_install")
            log.assert_called_once_with(title="hausverwaltung post-install patch failed (after_install)",
                                        patch=install._POST_INSTALL_PATCHES[0])
            for execute in executors:
                execute.assert_called_once_with()
            self.assertEqual(mark.call_args_list, [call(name) for name in install._POST_INSTALL_PATCHES[1:]])
            commit.assert_called_once_with()
