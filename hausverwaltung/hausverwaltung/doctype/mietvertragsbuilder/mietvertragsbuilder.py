# import frappe
import os

import frappe
import pdfkit
from frappe.model.document import Document
from frappe import safe_eval
from PyPDF2 import PdfMerger


def _render_html_to_pdf(html: str, output_path: str) -> None:
	"""Helper to render a small HTML snippet to a PDF file."""
	pdfkit.from_string(html, output_path, options={"quiet": ""})


class Mietvertragsbuilder(Document):
	def _build_html_and_attachments(self) -> tuple[str, list[str]]:
		"""Create HTML for all visible text blocks and collect attachments."""

		html_parts: list[str] = []
		attachments: list[str] = []
		paragraph = 1

		for block in self.textbausteine:
			visible = True
			if block.sichtbar_wenn:
				try:
					visible = safe_eval(block.sichtbar_wenn, {"doc": self.as_dict()})
				except Exception:
					visible = False

			if not visible:
				continue

			title = block.name1 or ""
			html_parts.append(f"<h3>§{paragraph} {title}</h3>")
			html_parts.append(block.text_html or "")
			paragraph += 1

			if block.link_auty:
				path = frappe.get_site_path("public", block.link_auty)
				if os.path.exists(path):
					attachments.append(path)

		return "\n".join(html_parts), attachments

	@frappe.whitelist()
	def generiere_mietvertrag_pdf(self) -> str:
		"""Builds the contract PDF including numbered attachments."""

		html, attachments = self._build_html_and_attachments()

		main_pdf = f"/tmp/{self.name}_main.pdf"
		_render_html_to_pdf(html, main_pdf)

		merger = PdfMerger()
		merger.append(main_pdf)

		for idx, attachment in enumerate(attachments, start=1):
			label_pdf = f"/tmp/{self.name}_anhang_{idx}.pdf"
			_render_html_to_pdf(f"<h2>Anlage {idx}</h2>", label_pdf)
			merger.append(label_pdf)
			merger.append(attachment)

		final_path = frappe.get_site_path("public", "files", f"{self.name}_vertrag.pdf")
		merger.write(final_path)
		merger.close()

		frappe.get_doc(
			{
				"doctype": "File",
				"file_url": f"/files/{self.name}_vertrag.pdf",
				"attached_to_doctype": "Mietvertragsbuilder",
				"attached_to_name": self.name,
			}
		).insert()

		return f"/files/{self.name}_vertrag.pdf"
