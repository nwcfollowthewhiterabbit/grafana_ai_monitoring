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
        "mappings": [],
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
                    "spanNulls": True,
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
    app_scope = scope + ',stack=~"$application",stack!~"monitoring.*|node-exporter"'
    server_vector = f'max by (company,alias) (rs_monitoring_server_up{{{scope}}})'
    app_vector = f'max by (company,alias,stack) (rs_monitoring_application_up{{{app_scope}}})'
    variables = [
        query_var("company", "Company", "label_values(rs_monitoring_server_inventory_info, company)", multi=True, include_all=True),
        query_var("server", "Server", 'label_values(rs_monitoring_server_inventory_info{company=~"$company",server_status="active"}, alias)', multi=True, include_all=True),
        query_var("application", "Application", 'label_values(rs_monitoring_application_inventory_info{company=~"$company",alias=~"$server",application_status="active"}, stack)', multi=True, include_all=True),
    ]
    panels = [
        text_panel(1, "Operator view", "Start here: **what exists → where it runs → whether it works → active incident or due action**. Status panels use catalog-aware recording metrics; missing coverage remains visible rather than becoming green.", 0, 0, 24, 3),
        stat_panel(2, "Servers down", f"count({server_vector} == 0) or vector(0)", 0, 3, 4, 4, thresholds=[("green", None), ("red", 1)]),
        stat_panel(3, "Applications unhealthy", f"count({app_vector} == 0) or vector(0)", 4, 3, 4, 4, thresholds=[("green", None), ("red", 1)]),
        stat_panel(4, "Firing alerts", f'sum(rs_monitoring_alert_firing{{{scope}}}) or count(ALERTS{{alertstate="firing",{scope}}}) or vector(0)', 8, 3, 4, 4, thresholds=[("green", None), ("red", 1)]),
        stat_panel(5, "Open incidents", f'sum(rs_monitoring_open_incident{{{scope},state="open"}}) or vector(0)', 12, 3, 4, 4, thresholds=[("green", None), ("red", 1)], description="Strictly scoped to the selected company and server."),
        stat_panel(6, "Service events due ≤30d", f'count(rs_monitoring_service_event_due_timestamp_seconds{{{scope}}} < time() + 30 * 86400)', 16, 3, 4, 4, thresholds=[("green", None), ("yellow", 1), ("red", 5)], description="No data means the deadline registry has no verified entries; it is not interpreted as green coverage."),
        stat_panel(7, "TLS expires ≤30d", f'count((probe_ssl_earliest_cert_expiry{{job="blackbox_http_services",{app_scope}}} - time()) < 30 * 86400) or vector(0)', 20, 3, 4, 4, thresholds=[("green", None), ("yellow", 1), ("red", 5)]),
        table_panel(8, "Server status", [("A", server_vector, "{{company}} / {{alias}}")], 0, 7, 12, 8, description="1=reachable, 0=down.", data_link={"title": "Open server", "url": '/d/managed-server-drilldown/managed-server-drilldown?var-company=${__data.fields["company"]}&var-server=${__data.fields["alias"]}', "targetBlank": False}),
        table_panel(9, "Application status", [("A", app_vector, "{{company}} / {{alias}} / {{stack}}")], 12, 7, 12, 8, description="Application is healthy only when all observed components are running.", data_link={"title": "Open application", "url": '/d/managed-application-drilldown/managed-application-drilldown?var-company=${__data.fields["company"]}&var-server=${__data.fields["alias"]}&var-application=${__data.fields["stack"]}', "targetBlank": False}),
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
    app_scope = scope + ',stack=~"$application",stack!~"monitoring.*|node-exporter"'
    app_up = f'rs_monitoring_application_up{{{app_scope}}}'
    variables = [
        query_var("company", "Company", "label_values(rs_monitoring_server_inventory_info, company)"),
        query_var("server", "Server", 'label_values(rs_monitoring_server_inventory_info{company=~"$company",server_status="active"}, alias)'),
        query_var("application", "Application", 'label_values(rs_monitoring_application_inventory_info{company=~"$company",alias=~"$server",application_status="active"}, stack)', multi=True, include_all=True),
    ]
    panels = [
        text_panel(1, "Server workflow", "Confirm server reachability, identify the affected **application**, then inspect its aggregate resource rates and components. Network and block I/O are rates, never raw cumulative totals.", 0, 0, 24, 3),
        stat_panel(2, "Server up", f'max(rs_monitoring_server_up{{{scope}}})', 0, 3, 4, 4, thresholds=[("red", None), ("green", 1)], minimum=0, maximum=1),
        stat_panel(3, "Unhealthy applications", f"count({app_up} == 0) or vector(0)", 4, 3, 4, 4, thresholds=[("green", None), ("red", 1)]),
        stat_panel(4, "Running components", f'sum(rs_monitoring_component_up{{{app_scope}}}) or vector(0)', 8, 3, 4, 4),
        stat_panel(5, "RAM used", f'max(100 * rs_monitoring_server_memory_utilization_ratio{{{scope}}}) or max(100 * (1 - node_memory_MemAvailable_bytes{{job="node_exporter_clients",{scope}}} / node_memory_MemTotal_bytes{{job="node_exporter_clients",{scope}}}))', 12, 3, 4, 4, unit="percent", thresholds=[("green", None), ("yellow", 75), ("red", 90)], minimum=0, maximum=100),
        stat_panel(6, "Root disk free", f'min(100 * rs_monitoring_server_root_disk_free_ratio{{{scope}}}) or min(100 * node_filesystem_avail_bytes{{job="node_exporter_clients",{scope},mountpoint="/",fstype!~"tmpfs|overlay|squashfs"}} / node_filesystem_size_bytes{{job="node_exporter_clients",{scope},mountpoint="/",fstype!~"tmpfs|overlay|squashfs"}})', 16, 3, 4, 4, unit="percent", thresholds=[("red", None), ("yellow", 15), ("green", 25)], minimum=0, maximum=100),
        stat_panel(7, "Open incidents", f'sum(rs_monitoring_open_incident{{{scope},state="open"}}) or vector(0)', 20, 3, 4, 4, thresholds=[("green", None), ("red", 1)]),
        table_panel(8, "Applications on server", [("A", app_up, "{{stack}}")], 0, 7, 12, 8, data_link={"title": "Open application", "url": '/d/managed-application-drilldown/managed-application-drilldown?var-company=$company&var-server=$server&var-application=${__data.fields["stack"]}', "targetBlank": False}),
        table_panel(9, "Components on server", [("A", f'max by (company,alias,stack,service,container) (rs_monitoring_component_up{{{app_scope}}})', "{{stack}} / {{service}} / {{container}}")], 12, 7, 12, 8, description="Expected catalog components observed in the runtime; 1=running."),
        timeseries_panel(10, "CPU by application", [("A", f'max by (company,alias,stack) (rs_monitoring_application_cpu_percent{{{app_scope}}}) or sum by (company,alias,stack) (docker_stack_container_cpu_percent{{{app_scope},state="running"}})', "{{stack}}")], 0, 15, 12, 8, unit="percent"),
        timeseries_panel(11, "RAM by application", [("A", f'max by (company,alias,stack) (rs_monitoring_application_memory_bytes{{{app_scope}}}) or sum by (company,alias,stack) (docker_stack_container_memory_usage_bytes{{{app_scope},state="running"}})', "{{stack}}")], 12, 15, 12, 8, unit="bytes"),
        timeseries_panel(12, "Network rate by application", [
            ("A", f'max by (company,alias,stack) (rs_monitoring_application_network_rx_bytes_per_second{{{app_scope}}}) or sum by (company,alias,stack) (clamp_min(rate(docker_stack_container_net_rx_bytes{{{app_scope},state="running"}}[15m]), 0))', "{{stack}} RX"),
            ("B", f'max by (company,alias,stack) (rs_monitoring_application_network_tx_bytes_per_second{{{app_scope}}}) or sum by (company,alias,stack) (clamp_min(rate(docker_stack_container_net_tx_bytes{{{app_scope},state="running"}}[15m]), 0))', "{{stack}} TX"),
        ], 0, 23, 12, 8, unit="Bps", description="Fallback derives rates from cumulative Docker exporter values over 15 minutes."),
        timeseries_panel(13, "Block I/O rate by application", [
            ("A", f'max by (company,alias,stack) (rs_monitoring_application_block_read_bytes_per_second{{{app_scope}}}) or sum by (company,alias,stack) (clamp_min(rate(docker_stack_container_block_read_bytes{{{app_scope},state="running"}}[15m]), 0))', "{{stack}} read"),
            ("B", f'max by (company,alias,stack) (rs_monitoring_application_block_write_bytes_per_second{{{app_scope}}}) or sum by (company,alias,stack) (clamp_min(rate(docker_stack_container_block_write_bytes{{{app_scope},state="running"}}[15m]), 0))', "{{stack}} write"),
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
    app_up = f'rs_monitoring_application_up{{{scope}}}'
    component_up = f'max by (company,alias,stack,service,container) (rs_monitoring_component_up{{{component_scope}}})'
    variables = [
        query_var("company", "Company", "label_values(rs_monitoring_server_inventory_info, company)"),
        query_var("server", "Server", 'label_values(rs_monitoring_server_inventory_info{company=~"$company",server_status="active"}, alias)'),
        query_var("application", "Application", 'label_values(rs_monitoring_application_inventory_info{company=~"$company",alias=~"$server",application_status="active"}, stack)'),
        query_var("component", "Component", 'label_values(rs_monitoring_expected_component_info{company=~"$company",alias=~"$server",stack=~"$application"}, service)', multi=True, include_all=True),
        query_var("container", "Container", 'label_values(rs_monitoring_component_up{company=~"$company",alias=~"$server",stack=~"$application",service=~"$component"}, container)', multi=True, include_all=True),
    ]
    panels = [
        text_panel(1, "Application workflow", "Treat infrastructure and external experience as independent signals. A healthy container does not prove the site works. Use the HTTP, integrity, TLS and backup panels and links after checking components.", 0, 0, 24, 3),
        stat_panel(2, "Application up", app_up, 0, 3, 4, 4, thresholds=[("red", None), ("green", 1)], minimum=0, maximum=1),
        stat_panel(3, "Running components", f'sum({component_up}) or vector(0)', 4, 3, 4, 4),
        stat_panel(4, "Stopped components", f'count({component_up} == 0) or vector(0)', 8, 3, 4, 4, thresholds=[("green", None), ("red", 1)]),
        stat_panel(5, "HTTP up", f'min(rs_monitoring_http_up{{{scope}}}) or min(probe_success{{job="blackbox_http_services",{scope}}})', 12, 3, 3, 4, thresholds=[("red", None), ("green", 1)], minimum=0, maximum=1),
        stat_panel(6, "Integrity up", f'min(rs_monitoring_integrity_up{{{scope}}})', 15, 3, 3, 4, thresholds=[("red", None), ("green", 1)], minimum=0, maximum=1, description="Independent twice-daily heuristic check; No data is not interpreted as healthy."),
        stat_panel(7, "TLS days left", f'min((rs_monitoring_tls_expiry_timestamp_seconds{{{scope}}} or probe_ssl_earliest_cert_expiry{{job="blackbox_http_services",{scope}}}) - time()) / 86400', 18, 3, 3, 4, unit="dtdurations", thresholds=[("red", None), ("yellow", 14), ("green", 30)]),
        stat_panel(8, "Backup age", f'min((time() - rs_monitoring_backup_last_success_timestamp_seconds{{{scope}}}) / 3600)', 21, 3, 3, 4, unit="h", thresholds=[("green", None), ("yellow", 24), ("red", 48)], description="No data until a verified backup signal is normalized for this application."),
        table_panel(9, "Component state", [("A", component_up, "{{service}} / {{container}}")], 0, 7, 12, 8, description="Catalog-expected components matched to observed Docker containers."),
        table_panel(10, "External checks", [
            ("A", f'rs_monitoring_http_up{{{scope}}} or probe_success{{job="blackbox_http_services",{scope}}}', "HTTP · {{instance}}"),
            ("B", f'rs_monitoring_integrity_up{{{scope}}}', "Integrity · {{instance}}"),
            ("C", f'((rs_monitoring_tls_expiry_timestamp_seconds{{{scope}}} or probe_ssl_earliest_cert_expiry{{job="blackbox_http_services",{scope}}}) - time()) / 86400', "TLS days · {{instance}}"),
            ("D", f'(time() - rs_monitoring_backup_last_success_timestamp_seconds{{{scope}}}) / 3600', "Backup age hours · {{stack}}"),
        ], 12, 7, 12, 8, description="Independent external and continuity signals; missing planned metrics remain visibly No data."),
        timeseries_panel(11, "CPU by component", [("A", f'max by (company,alias,stack,service,container) (rs_monitoring_component_cpu_percent{{{component_scope}}}) or max by (company,alias,stack,service,container) (docker_stack_container_cpu_percent{{{component_scope},state="running"}})', "{{service}} / {{container}}")], 0, 15, 12, 8, unit="percent"),
        timeseries_panel(12, "RAM by component", [("A", f'max by (company,alias,stack,service,container) (rs_monitoring_component_memory_bytes{{{component_scope}}}) or max by (company,alias,stack,service,container) (docker_stack_container_memory_usage_bytes{{{component_scope},state="running"}})', "{{service}} / {{container}}")], 12, 15, 12, 8, unit="bytes"),
        timeseries_panel(13, "Network rate by component", [
            ("A", f'max by (company,alias,stack,service,container) (rs_monitoring_component_network_rx_bytes_per_second{{{component_scope}}}) or max by (company,alias,stack,service,container) (clamp_min(rate(docker_stack_container_net_rx_bytes{{{component_scope},state="running"}}[15m]), 0))', "{{service}} / {{container}} RX"),
            ("B", f'max by (company,alias,stack,service,container) (rs_monitoring_component_network_tx_bytes_per_second{{{component_scope}}}) or max by (company,alias,stack,service,container) (clamp_min(rate(docker_stack_container_net_tx_bytes{{{component_scope},state="running"}}[15m]), 0))', "{{service}} / {{container}} TX"),
        ], 0, 23, 12, 8, unit="Bps"),
        timeseries_panel(14, "Block I/O rate by component", [
            ("A", f'max by (company,alias,stack,service,container) (rs_monitoring_component_block_read_bytes_per_second{{{component_scope}}}) or max by (company,alias,stack,service,container) (clamp_min(rate(docker_stack_container_block_read_bytes{{{component_scope},state="running"}}[15m]), 0))', "{{service}} / {{container}} read"),
            ("B", f'max by (company,alias,stack,service,container) (rs_monitoring_component_block_write_bytes_per_second{{{component_scope}}}) or max by (company,alias,stack,service,container) (clamp_min(rate(docker_stack_container_block_write_bytes{{{component_scope},state="running"}}[15m]), 0))', "{{service}} / {{container}} write"),
        ], 12, 23, 12, 8, unit="Bps"),
        text_panel(15, "Operational links", "[HTTP availability](/d/service-availability/service-availability?var-company=$company&var-node=$server&var-stack=$application) · [Backup detail](/d/cloud-backups/cloud-backups) · [Server drilldown](/d/managed-server-drilldown/managed-server-drilldown?var-company=$company&var-server=$server&var-application=$application)\n\nIntegrity evidence is an independent heuristic signal. Service deadlines remain No data until their dates and owners are verified in the catalog.", 0, 31, 24, 4),
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
