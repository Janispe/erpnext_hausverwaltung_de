# Basis-Image + Chromium-Systembibliotheken für die PDF-Engine "chrome".
# Identisch zum Produktiv-Dockerfile, damit Dev denselben Render-Pfad testet.
ARG FRAPPE_BASE_IMAGE=frappe/erpnext:v16.14.0
FROM ${FRAPPE_BASE_IMAGE}

# System libraries für Chromium-Headless (PDF Generator "chrome").
# Frappe lädt das Chromium-Binary automatisch nach
# /home/frappe/frappe-bench/chromium/, braucht aber die GTK/Cups/NSS-Stack
# als shared libraries.
USER root
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		libatk-bridge2.0-0 \
		libatk1.0-0 \
		libcups2 \
		libdrm2 \
		libxkbcommon0 \
		libxcomposite1 \
		libxdamage1 \
		libxfixes3 \
		libxrandr2 \
		libgbm1 \
		libpango-1.0-0 \
		libcairo2 \
		libasound2 \
		libnss3 \
		fonts-liberation \
	&& rm -rf /var/lib/apt/lists/*
USER frappe
