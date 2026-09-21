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
FAC_CODE_TOOL_NAMES = ("hv_export_view", "agent_mail_merge_get_pdf")

# Controlled mail merge: the only FAC tools that write. They store drafts from a previously checked
# preview (preparation token); nothing is sent or submitted. See docs/llm-serienbriefe.md.
FAC_MAIL_MERGE_TOOL_NAMES = (
	"agent_mail_merge_list_templates",
	"agent_mail_merge_get_template",
	"agent_mail_merge_prepare",
	"agent_mail_merge_execute",
	"agent_mail_merge_get_status",
)

# Hook imports are resolved by FAC only when its custom_tools plugin is enabled.
FAC_TOOL_HOOKS = [
	f"hausverwaltung.hausverwaltung.agent_tools.fac_tools.Fac_{name}"
	for name in (*FAC_TOOL_NAMES, *FAC_CODE_TOOL_NAMES, *FAC_MAIL_MERGE_TOOL_NAMES)
]
