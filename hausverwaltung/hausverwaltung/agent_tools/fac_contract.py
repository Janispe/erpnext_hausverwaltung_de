"""Optional FAC pilot: an explicit, read-only tool surface shared by both clients."""

FAC_TOOL_NAMES = (
	"hv_describe_query_sources",
	"hv_describe_query_source",
	"search_mieter",
	"get_mieter_context",
	"get_mieterkonto_summary",
	"search_open_items",
	"search_late_payments",
	"rank_mieter_by_rent",
	"analyze_revenue_over_time",
	"hv_query_docs",
	"hv_query_view",
	"hv_get_doc",
	"agent_describe_data_catalog",
	"agent_list_doctypes",
	"agent_get_doctype_schema",
	"agent_list_docs",
	"agent_get_doc",
	"agent_search_docs",
)

# Bulk tools for code callers (e.g. LibreChat run_tools_with_bash). Their results are too large for a
# model context, so they are not part of FAC_TOOL_NAMES, which the built-in FAC engines offer to the model.
FAC_CODE_TOOL_NAMES = ("hv_export_view", "hv_export_report", "agent_mail_merge_get_pdf")

# ERPNext reports (General Ledger, Accounts Receivable, own script reports, ...), read-only and paged.
# FAC's own report tools return unbounded output; these wrap them with limits for external clients.
FAC_REPORT_TOOL_NAMES = ("hv_report_list", "hv_report_requirements", "hv_run_report")

# Controlled mail merge: the only FAC tools that write. They store drafts: saved inputs (save_draft,
# update_draft) or PDFs from a previously checked preview (execute); nothing is sent or submitted.
# See docs/llm-serienbriefe.md.
FAC_MAIL_MERGE_TOOL_NAMES = (
	"agent_mail_merge_create_template",
	"agent_mail_merge_propose_template_version",
	"agent_mail_merge_list_template_versions",
	"agent_mail_merge_list_templates",
	"agent_mail_merge_get_template",
	"agent_mail_merge_prepare",
	"agent_mail_merge_execute",
	"agent_mail_merge_get_status",
	"agent_mail_merge_save_draft",
	"agent_mail_merge_get_draft",
	"agent_mail_merge_list_drafts",
	"agent_mail_merge_update_draft",
)
FAC_MAIL_MERGE_WRITE_TOOL_NAMES = (
	"agent_mail_merge_create_template",
	"agent_mail_merge_propose_template_version",
	"agent_mail_merge_execute",
	"agent_mail_merge_save_draft",
	"agent_mail_merge_update_draft",
)

# Hook imports are resolved by FAC only when its custom_tools plugin is enabled.
FAC_TOOL_HOOKS = [
	f"hausverwaltung.hausverwaltung.agent_tools.fac_tools.Fac_{name}"
	for name in (*FAC_TOOL_NAMES, *FAC_REPORT_TOOL_NAMES, *FAC_CODE_TOOL_NAMES, *FAC_MAIL_MERGE_TOOL_NAMES)
]
