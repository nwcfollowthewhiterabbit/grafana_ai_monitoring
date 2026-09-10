#!/usr/bin/env python3
"""Generate the managed-monitoring v2 admin and Greenleaf Grafana dashboards."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
ADMIN_DIR = ROOT / "monitoring/grafana/provisioning/dashboards"
GREENLEAF_DIR = ROOT / "monitoring/grafana/provisioning/company-dashboards/greenleaf"
PROMETHEUS = {"type": "prometheus", "uid": "PBFA97CFB590B2093"}


def target(expr: str, legend: str = "", *, instant: bool = False, ref_id: str = "A", fmt: str = "time_series") -> dict:
    return {
        "datasource": PROMETHEUS,
        "editorMode": "code",
        "expr": expr,
        "format": fmt,
        "instant": instant,
        "legendFormat": legend,
        "range": not instant,
        "refId": ref_id,
    }


def field_config(unit: str = "short", *, minimum: Optional[float] = None, maximum: Optional[float] = None,
                 thresholds: Optional[list[tuple[str, Optional[float]]]] = None,
                 links: Optional[list[dict]] = None) -> dict:
    defaults: dict = {
        "color": {"mode": "thresholds"},
        "mappings": [
            {"type": "special", "options": {"match": "null", "result": {"text": "UNKNOWN", "color": "gray"}}},
            {"type": "special", "options": {"match": "nan", "result": {"text": "UNKNOWN", "color": "gray"}}},
        ],
        "noValue": "UNKNOWN",
        "thresholds": {
            "mode": "absolute",
            "steps": [
                {"color": color, "value": value}
                for color, value in (thresholds or [("green", None)])
            ],
        },
        "unit": unit,
    }
    if minimum is not None:
        defaults["min"] = minimum
    if maximum is not None:
        defaults["max"] = maximum
    if links:
        defaults["links"] = links
    return {"defaults": defaults, "overrides": []}


def state_panel(panel: dict, *, positive: str = "RUNNING", negative: str = "STOPPED / MISSING") -> dict:
    """Render the explicit -1/0/1 status contract; absence never looks healthy."""
    defaults = panel["fieldConfig"]["defaults"]
    defaults["mappings"] = [
        {"type": "value", "options": {
            "-1": {"text": "UNKNOWN", "color": "gray", "index": 0},
            "0": {"text": negative, "color": "red", "index": 1},
            "1": {"text": positive, "color": "green", "index": 2},
        }},
        {"type": "special", "options": {"match": "null", "result": {"text": "UNKNOWN", "color": "gray"}}},
    ]
    defaults["thresholds"]["steps"] = [
        {"color": "gray", "value": None}, {"color": "red", "value": 0}, {"color": "green", "value": 1},
    ]
    return panel


def status_count(vector: str, comparison: str) -> str:
    # A zero needs inventory evidence. An empty recording rule is UNKNOWN.
    return f"count({vector} {comparison}) or (0 * count({vector}))"


def incident_count(scope: str) -> str:
    available = 'max(rs_monitoring_incident_pipeline_available{company=~"$company"}) == 1'
    return f'(sum(rs_monitoring_open_incident{{{scope},state="open"}}) or (0 * ({available}))) and on () ({available})'


def text_panel(panel_id: int, title: str, content: str, x: int, y: int, w: int, h: int) -> dict:
    return {
        "id": panel_id,
        "type": "text",
        "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {"mode": "markdown", "content": content},
    }


def stat_panel(panel_id: int, title: str, expr: str, x: int, y: int, w: int, h: int, *,
               unit: str = "short", description: str = "",
               thresholds: Optional[list[tuple[str, Optional[float]]]] = None,
               minimum: Optional[float] = None, maximum: Optional[float] = None) -> dict:
    return {
        "id": panel_id,
        "type": "stat",
        "title": title,
        "description": description,
        "datasource": PROMETHEUS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": field_config(unit, minimum=minimum, maximum=maximum, thresholds=thresholds),
        "options": {
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
            "wideLayout": True,
        },
        "targets": [target(expr, instant=True)],
    }


def table_panel(panel_id: int, title: str, queries: list[tuple[str, str, str]], x: int, y: int, w: int, h: int, *,
                description: str = "", data_link: Optional[dict] = None) -> dict:
    return {
        "id": panel_id,
        "type": "table",
        "title": title,
        "description": description,
        "datasource": PROMETHEUS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": field_config(links=[data_link] if data_link else None),
        "options": {
            "cellHeight": "sm",
            "footer": {"countRows": False, "fields": "", "reducer": ["sum"], "show": False},
            "showHeader": True,
        },
        "targets": [target(expr, legend, instant=True, ref_id=ref_id, fmt="table") for ref_id, expr, legend in queries],
        "transformations": [],
    }


def timeseries_panel(panel_id: int, title: str, queries: list[tuple[str, str, str]], x: int, y: int, w: int, h: int, *,
                     unit: str = "short", description: str = "") -> dict:
    return {
        "id": panel_id,
        "type": "timeseries",
        "title": title,
        "description": description,
        "datasource": PROMETHEUS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "custom": {
                    "axisCenteredZero": False,
                    "axisColorMode": "text",
                    "axisLabel": "",
                    "axisPlacement": "auto",
                    "barAlignment": 0,
                    "drawStyle": "line",
                    "fillOpacity": 8,
                    "gradientMode": "none",
                    "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                    "lineInterpolation": "linear",
                    "lineWidth": 1,
                    "pointSize": 4,
                    "scaleDistribution": {"type": "linear"},
                    "showPoints": "never",
                    "spanNulls": False,
                    "stacking": {"group": "A", "mode": "none"},
                    "thresholdsStyle": {"mode": "off"},
                },
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
                "unit": unit,
            },
            "overrides": [],
        },
        "options": {
            "legend": {"calcs": ["lastNotNull"], "displayMode": "table", "placement": "bottom", "showLegend": True},
            "tooltip": {"hideZeros": False, "mode": "multi", "sort": "desc"},
        },
        "targets": [target(expr, legend, ref_id=ref_id) for ref_id, expr, legend in queries],
    }


def query_var(name: str, label: str, query: str, *, multi: bool = False, include_all: bool = False) -> dict:
    var = {
        "name": name,
        "label": label,
        "type": "query",
        "datasource": PROMETHEUS,
        "definition": query,
        "query": {"query": query, "refId": f"var-{name}"},
        "refresh": 1,
        "sort": 1,
        "multi": multi,
        "includeAll": include_all,
        "options": [],
        "current": {},
    }
    if include_all:
        var["allValue"] = ".*"
        var["current"] = {"selected": True, "text": "All", "value": "$__all"}
    return var


def dashboard(title: str, uid: str, description: str, variables: list[dict], panels: list[dict], links: list[dict]) -> dict:
    return {
        "annotations": {
            "list": [{
                "builtIn": 1,
                "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                "enable": True,
                "hide": True,
                "iconColor": "rgba(0, 211, 255, 1)",
                "name": "Annotations & Alerts",
                "type": "dashboard",
            }]
        },
        "description": description,
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": links,
        "liveNow": False,
        "panels": panels,
        "refresh": "1m",
        "schemaVersion": 41,
        "tags": ["rabbit-systems", "managed-monitoring", "operational", "v2"],
        "templating": {"list": variables},
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": title,
        "uid": uid,
        "version": 1,
        "weekStart": "",
    }


def dashboard_link(title: str, uid: str, slug: str, params: str = "") -> dict:
    suffix = f"?{params}" if params else ""
    return {
        "asDropdown": False,
        "icon": "external link",
        "includeVars": False,
        "keepTime": True,
        "tags": [],
        "targetBlank": False,
        "title": title,
        "tooltip": "",
        "type": "link",
        "url": f"/d/{uid}/{slug}{suffix}",
    }


def build_fleet() -> dict:
    scope = 'company=~"$company",alias=~"$server"'
    app_scope = scope + ',stack=~"$application"'
    server_vector = f'max by (company,alias) (rs_monitoring_server_status{{{scope}}})'
    app_vector = f'max by (company,alias,stack) (rs_monitoring_application_status{{{app_scope}}})'
    variables = [
        query_var("company", "Company", "label_values(rs_monitoring_server_inventory_info, company)", multi=True, include_all=True),
        query_var("server", "Server", 'label_values(rs_monitoring_server_status{company=~"$company"}, alias)', multi=True, include_all=True),
        query_var("application", "Application", 'label_values(rs_monitoring_application_status{company=~"$company",alias=~"$server"}, stack)', multi=True, include_all=True),
    ]
    panels = [
        text_panel(1, "Operator view", "Start here: **what exists → where it runs → whether it works → active incident or due action**. Status panels use catalog-aware recording metrics; missing coverage remains visible rather than becoming green.", 0, 0, 24, 3),
        stat_panel(2, "Exporters unreachable", status_count(server_vector, "== 0"), 0, 3, 3, 4, thresholds=[("green", None), ("red", 1)]),
        stat_panel(3, "Apps stopped / missing", status_count(app_vector, "== 0"), 3, 3, 3, 4, thresholds=[("green", None), ("red", 1)]),
        stat_panel(4, "Firing alerts", f'count(ALERTS{{alertstate="firing",{scope}}}) or (0 * count({server_vector}))', 6, 3, 3, 4, thresholds=[("green", None), ("red", 1)]),
        stat_panel(5, "Open incidents", incident_count(scope), 9, 3, 3, 4, thresholds=[("green", None), ("red", 1)], description="Scoped to the selected company/server. Zero requires a reachable incident gateway; unavailable pipeline is UNKNOWN."),
        stat_panel(6, "Events due ≤30d", status_count(f'rs_monitoring_service_event_due_timestamp_seconds{{{scope}}}', '< time() + 30 * 86400'), 12, 3, 3, 4, thresholds=[("green", None), ("yellow", 1), ("red", 5)], description="UNKNOWN means no verified deadline entries in scope."),
        stat_panel(7, "TLS expires ≤30d", status_count(f'rs_monitoring_tls_expiry_timestamp_seconds{{{app_scope}}}', '< time() + 30 * 86400'), 15, 3, 3, 4, thresholds=[("green", None), ("yellow", 1), ("red", 5)]),
        stat_panel(12, "Servers UNKNOWN", status_count(server_vector, "< 0"), 18, 3, 3, 4, thresholds=[("green", None), ("yellow", 1)]),
        stat_panel(13, "Apps UNKNOWN", status_count(app_vector, "< 0"), 21, 3, 3, 4, thresholds=[("green", None), ("yellow", 1)]),
        state_panel(table_panel(8, "Server telemetry status", [("A", server_vector, "{{company}} / {{alias}}")], 0, 7, 12, 8, description="Exporter reachability; UNKNOWN includes missing targets and pending onboarding.", data_link={"title": "Open server", "url": '/d/managed-server-drilldown/managed-server-drilldown?var-company=${__data.fields["company"]}&var-server=${__data.fields["alias"]}', "targetBlank": False}), positive="REACHABLE", negative="UNREACHABLE"),
        state_panel(table_panel(9, "Application runtime status", [("A", app_vector, "{{company}} / {{alias}} / {{stack}}")], 12, 7, 12, 8, description="RUNNING means each expected service has at least one running container in fresh inventory. Docker healthchecks and external checks are separate. Missing/stale inventory is UNKNOWN.", data_link={"title": "Open application", "url": '/d/managed-application-drilldown/managed-application-drilldown?var-company=${__data.fields["company"]}&var-server=${__data.fields["alias"]}&var-application=${__data.fields["stack"]}', "targetBlank": False})),
        table_panel(10, "Open incident queue", [("A", f'rs_monitoring_open_incident{{{scope},state="open"}}', "{{severity}} · {{alias}} · {{stack}} · {{service}}"), ("B", f'ALERTS{{alertstate="firing",{scope}}}', "fallback alert · {{alertname}} · {{alias}}")], 0, 15, 12, 9, description="A is the bounded lifecycle aggregate. B is a raw Prometheus fallback and is not an incident."),
        table_panel(11, "Service-event queue", [("A", f'rs_monitoring_service_event_due_timestamp_seconds{{{scope}}} - time()', "{{event_type}} · {{alias}} · {{stack}}")], 12, 15, 12, 9, description="Seconds until domain, certificate, subscription or maintenance deadline."),
    ]
    links = [
        dashboard_link("Server drilldown", "managed-server-drilldown", "managed-server-drilldown", "var-company=$company&var-server=$server"),
        dashboard_link("Application drilldown", "managed-application-drilldown", "managed-application-drilldown", "var-company=$company&var-server=$server&var-application=$application"),
    ]
    return dashboard("Managed Monitoring · Fleet Overview", "managed-fleet-overview", "Rabbit Systems fleet operations across companies, servers, applications, incidents and service deadlines.", variables, panels, links)


def build_server() -> dict:
    scope = 'company=~"$company",alias=~"$server"'
    app_scope = scope + ',stack=~"$application"'
    app_up = f'rs_monitoring_application_status{{{app_scope}}}'
    variables = [
        query_var("company", "Company", "label_values(rs_monitoring_server_inventory_info, company)"),
        query_var("server", "Server", 'label_values(rs_monitoring_server_status{company=~"$company"}, alias)'),
        query_var("application", "Application", 'label_values(rs_monitoring_application_status{company=~"$company",alias=~"$server"}, stack)', multi=True, include_all=True),
    ]
    panels = [
        text_panel(1, "Server workflow", "Confirm server reachability, identify the affected **application**, then inspect its aggregate resource rates and components. Network and block I/O are rates, never raw cumulative totals.", 0, 0, 24, 3),
        state_panel(stat_panel(2, "Host telemetry", f'min(rs_monitoring_server_status{{{scope}}})', 0, 3, 4, 4), positive="REACHABLE", negative="UNREACHABLE"),
        stat_panel(3, "Apps stopped / missing", status_count(app_up, "== 0"), 4, 3, 4, 4, thresholds=[("green", None), ("red", 1)]),
        stat_panel(4, "Apps UNKNOWN", status_count(app_up, "< 0"), 8, 3, 4, 4, thresholds=[("green", None), ("yellow", 1)]),
        stat_panel(5, "RAM used", f'max(100 * rs_monitoring_server_memory_utilization_ratio{{{scope}}})', 12, 3, 4, 4, unit="percent", thresholds=[("green", None), ("yellow", 75), ("red", 90)], minimum=0, maximum=100),
        stat_panel(6, "Root disk free", f'min(100 * rs_monitoring_server_root_disk_free_ratio{{{scope}}})', 16, 3, 4, 4, unit="percent", thresholds=[("red", None), ("yellow", 15), ("green", 25)], minimum=0, maximum=100),
        stat_panel(7, "Open incidents", incident_count(scope), 20, 3, 4, 4, thresholds=[("green", None), ("red", 1)]),
        state_panel(table_panel(8, "Application runtime on server", [("A", app_up, "{{stack}}")], 0, 7, 12, 8, data_link={"title": "Open application", "url": '/d/managed-application-drilldown/managed-application-drilldown?var-company=$company&var-server=$server&var-application=${__data.fields["stack"]}', "targetBlank": False})),
        state_panel(table_panel(9, "Expected components on server", [("A", f'rs_monitoring_component_status{{{app_scope}}}', "{{stack}} / {{service}}")], 12, 7, 12, 8, description="One row per expected service, including missing containers. UNKNOWN when inventory is unavailable or older than 15 minutes.")),
        timeseries_panel(10, "CPU by application", [("A", f'rs_monitoring_application_cpu_percent{{{app_scope}}}', "{{stack}}")], 0, 15, 12, 8, unit="percent", description="Sum across containers; duplicate scrape series are deduplicated. CPU can exceed 100% across cores. Stale inventory creates a gap."),
        timeseries_panel(11, "RAM by application", [("A", f'rs_monitoring_application_memory_bytes{{{app_scope}}}', "{{stack}}")], 12, 15, 12, 8, unit="bytes"),
        timeseries_panel(12, "Network rate by application", [
            ("A", f'rs_monitoring_application_network_rx_bytes_per_second{{{app_scope}}}', "{{stack}} RX"),
            ("B", f'rs_monitoring_application_network_tx_bytes_per_second{{{app_scope}}}', "{{stack}} TX"),
        ], 0, 23, 12, 8, unit="Bps", description="Rates estimated over 15 minutes from Docker cumulative display values; inventory must be fresh."),
        timeseries_panel(13, "Block I/O rate by application", [
            ("A", f'rs_monitoring_application_block_read_bytes_per_second{{{app_scope}}}', "{{stack}} read"),
            ("B", f'rs_monitoring_application_block_write_bytes_per_second{{{app_scope}}}', "{{stack}} write"),
        ], 12, 23, 12, 8, unit="Bps", description="No raw lifetime block counters are displayed."),
        table_panel(14, "Incidents and raw alert fallback", [("A", f'rs_monitoring_open_incident{{{scope},state="open"}}', "{{severity}} · {{stack}} · {{service}}"), ("B", f'ALERTS{{alertstate="firing",{scope}}}', "fallback · {{alertname}}")], 0, 31, 24, 8),
    ]
    links = [
        dashboard_link("Fleet overview", "managed-fleet-overview", "managed-fleet-overview", "var-company=$company&var-server=$server"),
        dashboard_link("Application drilldown", "managed-application-drilldown", "managed-application-drilldown", "var-company=$company&var-server=$server&var-application=$application"),
    ]
    return dashboard("Managed Monitoring · Server Drilldown", "managed-server-drilldown", "Operational server view with application-level aggregation and component state.", variables, panels, links)


def build_application() -> dict:
    scope = 'company=~"$company",alias=~"$server",stack=~"$application"'
    component_scope = scope + ',service=~"$component",container=~"$container"'
    app_up = f'rs_monitoring_application_status{{{scope}}}'
    component_up = f'rs_monitoring_component_status{{{scope},service=~"$component"}}'
    variables = [
        query_var("company", "Company", "label_values(rs_monitoring_server_inventory_info, company)"),
        query_var("server", "Server", 'label_values(rs_monitoring_server_status{company=~"$company"}, alias)'),
        query_var("application", "Application", 'label_values(rs_monitoring_application_status{company=~"$company",alias=~"$server"}, stack)'),
        query_var("component", "Component", 'label_values(rs_monitoring_expected_component_info{company=~"$company",alias=~"$server",stack=~"$application"}, service)', multi=True, include_all=True),
        query_var("container", "Container", 'label_values(rs_monitoring_component_up{company=~"$company",alias=~"$server",stack=~"$application",service=~"$component"}, container)', multi=True, include_all=True),
    ]
    panels = [
        text_panel(1, "Application workflow", "Treat infrastructure and external experience as independent signals. A healthy container does not prove the site works. Use the HTTP, integrity, TLS and backup panels and links after checking components.", 0, 0, 24, 3),
        state_panel(stat_panel(2, "Application runtime", app_up, 0, 3, 4, 4, description="RUNNING requires at least one running container per expected service with fresh inventory. This does not evaluate Docker healthchecks.")),
        stat_panel(3, "Running services", status_count(component_up, "== 1"), 4, 3, 4, 4, description="Count of expected services with a running replica, not count of containers. UNKNOWN services are listed below."),
        stat_panel(4, "Services UNKNOWN", status_count(component_up, "< 0"), 8, 3, 4, 4, thresholds=[("green", None), ("yellow", 1)]),
        state_panel(stat_panel(5, "HTTP availability", f'min(rs_monitoring_http_up{{{scope}}})', 12, 3, 3, 4), positive="REACHABLE", negative="FAILED"),
        state_panel(stat_panel(6, "Integrity evidence", f'min(rs_monitoring_integrity_up{{{scope}}})', 15, 3, 3, 4, description="Independent twice-daily heuristic check. Evidence older than 25 hours is UNKNOWN."), positive="NO CONFIRMED PROBLEM", negative="PROBLEM"),
        stat_panel(7, "TLS days left", f'min(rs_monitoring_tls_expiry_timestamp_seconds{{{scope}}} - time()) / 86400', 18, 3, 3, 4, unit="d", thresholds=[("red", None), ("yellow", 14), ("green", 30)]),
        stat_panel(8, "Oldest backup age", f'max((time() - rs_monitoring_backup_last_success_timestamp_seconds{{{scope}}}) / 3600)', 21, 3, 3, 4, unit="h", thresholds=[("green", None), ("yellow", 24), ("red", 48)], description="Worst backup age; UNKNOWN until a verified signal is normalized for this application."),
        state_panel(table_panel(9, "Expected service runtime", [("A", component_up, "{{service}}")], 0, 7, 12, 8, description="Includes expected services with no observed container. Container selector affects resource panels only; it cannot hide a missing expected service.")),
        table_panel(10, "External checks", [
            ("A", f'rs_monitoring_http_up{{{scope}}}', "HTTP · {{instance}}"),
            ("B", f'rs_monitoring_integrity_up{{{scope}}}', "Integrity · {{instance}}"),
            ("C", f'(rs_monitoring_tls_expiry_timestamp_seconds{{{scope}}} - time()) / 86400', "TLS days · {{instance}}"),
            ("D", f'(time() - rs_monitoring_backup_last_success_timestamp_seconds{{{scope}}}) / 3600', "Backup age hours · {{stack}}"),
        ], 12, 7, 12, 8, description="Independent external and continuity signals; missing planned metrics remain visibly No data."),
        timeseries_panel(11, "CPU by component", [("A", f'rs_monitoring_component_cpu_percent{{{component_scope}}}', "{{service}} / {{container}}")], 0, 15, 12, 8, unit="percent"),
        timeseries_panel(12, "RAM by component", [("A", f'rs_monitoring_component_memory_bytes{{{component_scope}}}', "{{service}} / {{container}}")], 12, 15, 12, 8, unit="bytes"),
        timeseries_panel(13, "Network rate by component", [
            ("A", f'rs_monitoring_component_network_rx_bytes_per_second{{{component_scope}}}', "{{service}} / {{container}} RX"),
            ("B", f'rs_monitoring_component_network_tx_bytes_per_second{{{component_scope}}}', "{{service}} / {{container}} TX"),
        ], 0, 23, 12, 8, unit="Bps"),
        timeseries_panel(14, "Block I/O rate by component", [
            ("A", f'rs_monitoring_component_block_read_bytes_per_second{{{component_scope}}}', "{{service}} / {{container}} read"),
            ("B", f'rs_monitoring_component_block_write_bytes_per_second{{{component_scope}}}', "{{service}} / {{container}} write"),
        ], 12, 23, 12, 8, unit="Bps"),
        state_panel(table_panel(16, "Observed container runtime", [("A", f'rs_monitoring_component_up{{{component_scope}}}', "{{service}} / {{container}}")], 0, 31, 24, 8, description="Container-level running state from fresh inventory. Docker healthcheck state is not exported yet; inspect the application endpoint independently."), negative="STOPPED"),
        text_panel(15, "Operational links", "[HTTP availability](/d/service-availability/service-availability?var-company=$company&var-node=$server&var-stack=$application) · [Backup detail](/d/cloud-backups/cloud-backups) · [Server drilldown](/d/managed-server-drilldown/managed-server-drilldown?var-company=$company&var-server=$server&var-application=$application)\n\nIntegrity evidence is an independent heuristic signal. Service deadlines remain No data until their dates and owners are verified in the catalog.", 0, 39, 24, 4),
    ]
    links = [
        dashboard_link("Fleet overview", "managed-fleet-overview", "managed-fleet-overview", "var-company=$company&var-server=$server&var-application=$application"),
        dashboard_link("Server drilldown", "managed-server-drilldown", "managed-server-drilldown", "var-company=$company&var-server=$server&var-application=$application"),
        dashboard_link("HTTP availability", "service-availability", "service-availability", "var-company=$company&var-node=$server&var-stack=$application"),
        dashboard_link("Backup detail", "cloud-backups", "cloud-backups"),
    ]
    return dashboard("Managed Monitoring · Application Drilldown", "managed-application-drilldown", "Application/component diagnostics with independent HTTP, integrity, TLS and backup signals.", variables, panels, links)


def greenleaf_copy(source: dict, *, uid: str, title: str) -> dict:
    result = copy.deepcopy(source)
    result["uid"] = uid
    result["title"] = title
    result["editable"] = False
    result["tags"] = [*result["tags"], "greenleaf", "customer"]
    result["description"] += " Customer view is fixed to Greenleaf and is also enforced by the org-2 Prometheus label proxy."
    company = next(item for item in result["templating"]["list"] if item["name"] == "company")
    company.clear()
    company.update({
        "name": "company",
        "label": "Company",
        "type": "custom",
        "hide": 2,
        "query": "greenleaf",
        "multi": False,
        "includeAll": False,
        "current": {"selected": True, "text": "greenleaf", "value": "greenleaf"},
        "options": [{"selected": True, "text": "greenleaf", "value": "greenleaf"}],
    })
    replacements = {
        "/d/managed-fleet-overview/managed-fleet-overview": "/d/greenleaf-managed-fleet/managed-fleet-overview-greenleaf",
        "/d/managed-server-drilldown/managed-server-drilldown": "/d/greenleaf-managed-server/managed-server-drilldown-greenleaf",
        "/d/managed-application-drilldown/managed-application-drilldown": "/d/greenleaf-managed-application/managed-application-drilldown-greenleaf",
        "/d/service-availability/service-availability": "/d/greenleaf-service-availability/greenleaf-service-availability",
        "/d/cloud-backups/cloud-backups": "/d/greenleaf-cloud-backups/greenleaf-cloud-backups",
    }

    def replace_strings(value):
        if isinstance(value, str):
            for old, new in replacements.items():
                value = value.replace(old, new)
            return value
        if isinstance(value, list):
            return [replace_strings(item) for item in value]
        if isinstance(value, dict):
            return {key: replace_strings(item) for key, item in value.items()}
        return value

    return replace_strings(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated dashboards differ")
    args = parser.parse_args()
    ADMIN_DIR.mkdir(parents=True, exist_ok=True)
    GREENLEAF_DIR.mkdir(parents=True, exist_ok=True)
    dashboards = {
        "managed-fleet-overview.json": build_fleet(),
        "managed-server-drilldown.json": build_server(),
        "managed-application-drilldown.json": build_application(),
    }
    customer_meta = {
        "managed-fleet-overview.json": ("greenleaf-managed-fleet", "Rabbit Systems Managed Monitoring · Greenleaf Fleet"),
        "managed-server-drilldown.json": ("greenleaf-managed-server", "Rabbit Systems Managed Monitoring · Greenleaf Server"),
        "managed-application-drilldown.json": ("greenleaf-managed-application", "Rabbit Systems Managed Monitoring · Greenleaf Application"),
    }
    drift = []
    for filename, data in dashboards.items():
        admin_path = ADMIN_DIR / filename
        admin_content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        uid, title = customer_meta[filename]
        customer = greenleaf_copy(data, uid=uid, title=title)
        customer_path = GREENLEAF_DIR / filename
        customer_content = json.dumps(customer, indent=2, ensure_ascii=False) + "\n"
        if args.check:
            for path, content in ((admin_path, admin_content), (customer_path, customer_content)):
                if not path.exists() or path.read_text(encoding="utf-8") != content:
                    drift.append(str(path))
        else:
            admin_path.write_text(admin_content, encoding="utf-8")
            customer_path.write_text(customer_content, encoding="utf-8")
    if drift:
        raise SystemExit("generated dashboard drift: " + ", ".join(drift))


if __name__ == "__main__":
    main()
