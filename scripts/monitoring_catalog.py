#!/usr/bin/env python3
"""Strict loader and validator for the managed-monitoring service catalog."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

import yaml


CATALOG_VERSION = 2
ENTITY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
CRITICALITIES = {"low", "medium", "high", "critical"}
ENTITY_STATUSES = {"active", "pending_access", "pending_discovery", "disabled", "retired"}
OWNER_KINDS = {"provider", "customer", "vendor", "team"}
MONITORING_SIGNALS = {
	"availability",
	"backups",
	"containers",
	"integrity",
	"logs",
	"node",
	"service_events",
}
SERVICE_EVENT_TYPES = {"domain", "ssl", "subscription", "manual_renewal"}
SERVICE_EVENT_STATUSES = {"active", "date_unknown", "paused", "retired"}

ROOT_KEYS = {
	"version",
	"labels",
	"owners",
	"companies",
	"nodes",
	"http_services",
	"pending_discovery",
	"service_event_defaults",
	"service_events",
}
OWNER_KEYS = {"id", "display_name", "kind"}
COMPANY_KEYS = {
	"id",
	"label",
	"display_name",
	"owners",
	"customer_visible",
	"repository",
	"runbook",
	"monitoring",
	"servers",
}
SERVER_KEYS = {
	"id",
	"alias",
	"display_name",
	"role",
	"status",
	"owners",
	"customer_visible",
	"repository",
	"runbook",
	"monitoring",
	"applications",
}
APPLICATION_KEYS = {
	"id",
	"stack",
	"display_name",
	"status",
	"owners",
	"customer_visible",
	"repository",
	"runbook",
	"monitoring",
	"components",
}
COMPONENT_KEYS = {
	"id",
	"service",
	"display_name",
	"expected",
	"owners",
	"customer_visible",
	"repository",
	"runbook",
	"monitoring",
}
MONITORING_KEYS = {
	"enabled",
	"signals",
	"availability_interval_seconds",
	"integrity_interval_seconds",
	"retry_count",
	"retry_interval_seconds",
	"failure_threshold",
	"consecutive_bad_cycles",
}
LEGACY_NODE_KEYS = {"alias", "company", "role", "status", "network"}
HTTP_SERVICE_KEYS = {
	"company",
	"alias",
	"stack",
	"service",
	"url",
	"criticality",
	"monitoring",
}
HTTP_MONITORING_KEYS = {"enabled", "availability", "integrity"}
PENDING_DISCOVERY_KEYS = {"company", "alias", "stacks"}
EVENT_DEFAULT_KEYS = {"admin_lead_days", "customer_lead_days"}
SERVICE_EVENT_KEYS = {
	"id",
	"type",
	"title",
	"company",
	"server",
	"application",
	"component",
	"due_at",
	"status",
	"owners",
	"customer_visible",
	"repository",
	"runbook",
	"notes",
}


class CatalogValidationError(ValueError):
	"""Raised when catalog validation returns one or more errors."""

	def __init__(self, errors: Iterable[str]):
		self.errors = tuple(errors)
		super().__init__("; ".join(self.errors))


def _is_mapping(value: Any) -> bool:
	return isinstance(value, Mapping)


def _expect_mapping(value: Any, path: str, errors: list[str]) -> Mapping[str, Any]:
	if not _is_mapping(value):
		errors.append(f"{path}: expected mapping")
		return {}
	return value


def _expect_list(value: Any, path: str, errors: list[str]) -> list[Any]:
	if not isinstance(value, list):
		errors.append(f"{path}: expected list")
		return []
	return value


def _reject_unknown(mapping: Mapping[str, Any], allowed: set[str], path: str, errors: list[str]) -> None:
	for key in sorted(set(mapping) - allowed):
		errors.append(f"{path}: unknown field {key!r}")


def _require(mapping: Mapping[str, Any], keys: Iterable[str], path: str, errors: list[str]) -> None:
	for key in keys:
		if key not in mapping:
			errors.append(f"{path}: missing required field {key!r}")


def _validate_id(value: Any, path: str, errors: list[str]) -> str:
	if not isinstance(value, str) or not ENTITY_ID_RE.fullmatch(value):
		errors.append(f"{path}: expected lowercase stable id matching {ENTITY_ID_RE.pattern}")
		return ""
	return value


def _validate_nonempty_string(value: Any, path: str, errors: list[str]) -> str:
	if not isinstance(value, str) or not value.strip():
		errors.append(f"{path}: expected non-empty string")
		return ""
	return value.strip()


def _validate_optional_string(value: Any, path: str, errors: list[str]) -> None:
	if value is not None and (not isinstance(value, str) or not value.strip()):
		errors.append(f"{path}: expected null or non-empty string")


def _validate_bool(value: Any, path: str, errors: list[str]) -> None:
	if not isinstance(value, bool):
		errors.append(f"{path}: expected boolean")


def _validate_positive_int(value: Any, path: str, errors: list[str], *, allow_zero: bool = False) -> None:
	minimum = 0 if allow_zero else 1
	if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
		errors.append(f"{path}: expected integer >= {minimum}")


def _validate_owner_refs(value: Any, path: str, owner_ids: set[str], errors: list[str]) -> None:
	refs = _expect_list(value, path, errors)
	if not refs:
		errors.append(f"{path}: at least one owner is required")
	for index, owner_id in enumerate(refs):
		if not isinstance(owner_id, str) or owner_id not in owner_ids:
			errors.append(f"{path}[{index}]: unknown owner id {owner_id!r}")
	if len(refs) != len(set(refs)):
		errors.append(f"{path}: duplicate owner ids")


def _validate_monitoring(value: Any, path: str, errors: list[str]) -> None:
	policy = _expect_mapping(value, path, errors)
	_reject_unknown(policy, MONITORING_KEYS, path, errors)
	_require(policy, ("enabled", "signals"), path, errors)
	if "enabled" in policy:
		_validate_bool(policy["enabled"], f"{path}.enabled", errors)
	signals = _expect_list(policy.get("signals"), f"{path}.signals", errors)
	for index, signal in enumerate(signals):
		if signal not in MONITORING_SIGNALS:
			errors.append(f"{path}.signals[{index}]: unsupported signal {signal!r}")
	if len(signals) != len(set(signals)):
		errors.append(f"{path}.signals: duplicate values")
	for key in (
		"availability_interval_seconds",
		"integrity_interval_seconds",
		"retry_interval_seconds",
		"failure_threshold",
		"consecutive_bad_cycles",
	):
		if key in policy:
			_validate_positive_int(policy[key], f"{path}.{key}", errors)
	if "retry_count" in policy:
		_validate_positive_int(policy["retry_count"], f"{path}.retry_count", errors, allow_zero=True)
	if "failure_threshold" in policy and "retry_count" in policy:
		if (
			isinstance(policy["failure_threshold"], int)
			and isinstance(policy["retry_count"], int)
			and policy["failure_threshold"] > policy["retry_count"] + 1
		):
			errors.append(f"{path}.failure_threshold: cannot exceed retry_count + 1")


def _validate_common_entity(
	entity: Mapping[str, Any],
	path: str,
	owner_ids: set[str],
	errors: list[str],
) -> None:
	_validate_nonempty_string(entity.get("display_name"), f"{path}.display_name", errors)
	_validate_owner_refs(entity.get("owners"), f"{path}.owners", owner_ids, errors)
	_validate_bool(entity.get("customer_visible"), f"{path}.customer_visible", errors)
	_validate_optional_string(entity.get("repository"), f"{path}.repository", errors)
	_validate_optional_string(entity.get("runbook"), f"{path}.runbook", errors)
	_validate_monitoring(entity.get("monitoring"), f"{path}.monitoring", errors)


def parse_due_at(value: Any) -> dt.datetime | None:
	"""Parse a catalog due date as an aware UTC datetime."""

	if value is None:
		return None
	if isinstance(value, dt.datetime):
		parsed = value
	elif isinstance(value, dt.date):
		parsed = dt.datetime.combine(value, dt.time.min, tzinfo=dt.timezone.utc)
	elif isinstance(value, str):
		text = value.strip()
		if not text:
			return None
		try:
			if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
				parsed = dt.datetime.fromisoformat(text).replace(tzinfo=dt.timezone.utc)
			else:
				parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
		except ValueError as exc:
			raise ValueError("expected ISO-8601 date or timestamp") from exc
	else:
		raise ValueError("expected ISO-8601 date or timestamp")
	if parsed.tzinfo is None:
		raise ValueError("timestamp must include a timezone")
	return parsed.astimezone(dt.timezone.utc)


def _validate_lead_days(value: Any, path: str, errors: list[str]) -> None:
	days = _expect_list(value, path, errors)
	for index, day in enumerate(days):
		_validate_positive_int(day, f"{path}[{index}]", errors, allow_zero=True)
	if len(days) != len(set(days)):
		errors.append(f"{path}: duplicate lead days")
	if all(isinstance(day, int) and not isinstance(day, bool) for day in days):
		if days != sorted(days, reverse=True):
			errors.append(f"{path}: lead days must be in descending order")


def validate_catalog(catalog: Any) -> list[str]:
	"""Return every structural and referential validation error in a catalog."""

	errors: list[str] = []
	root = _expect_mapping(catalog, "catalog", errors)
	_reject_unknown(root, ROOT_KEYS, "catalog", errors)
	_require(
		root,
		(
			"version",
			"labels",
			"owners",
			"companies",
			"nodes",
			"http_services",
			"pending_discovery",
			"service_event_defaults",
			"service_events",
		),
		"catalog",
		errors,
	)
	if root.get("version") != CATALOG_VERSION:
		errors.append(f"catalog.version: expected {CATALOG_VERSION}")

	labels = _expect_mapping(root.get("labels"), "catalog.labels", errors)
	_reject_unknown(labels, {"required", "company_values"}, "catalog.labels", errors)
	_require(labels, ("required", "company_values"), "catalog.labels", errors)
	required_labels = _expect_list(labels.get("required"), "catalog.labels.required", errors)
	for required in ("company", "alias", "stack", "service", "criticality"):
		if required not in required_labels:
			errors.append(f"catalog.labels.required: missing {required!r}")
	company_values = _expect_list(labels.get("company_values"), "catalog.labels.company_values", errors)
	if len(company_values) != len(set(company_values)):
		errors.append("catalog.labels.company_values: duplicate values")

	owner_ids: set[str] = set()
	for index, raw_owner in enumerate(_expect_list(root.get("owners"), "catalog.owners", errors)):
		path = f"catalog.owners[{index}]"
		owner = _expect_mapping(raw_owner, path, errors)
		_reject_unknown(owner, OWNER_KEYS, path, errors)
		_require(owner, OWNER_KEYS, path, errors)
		owner_id = _validate_id(owner.get("id"), f"{path}.id", errors)
		if owner_id in owner_ids:
			errors.append(f"{path}.id: duplicate owner id {owner_id!r}")
		owner_ids.add(owner_id)
		_validate_nonempty_string(owner.get("display_name"), f"{path}.display_name", errors)
		if owner.get("kind") not in OWNER_KINDS:
			errors.append(f"{path}.kind: unsupported kind {owner.get('kind')!r}")

	companies_by_id: dict[str, Mapping[str, Any]] = {}
	companies_by_label: dict[str, Mapping[str, Any]] = {}
	servers_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
	applications_by_key: dict[tuple[str, str, str], Mapping[str, Any]] = {}
	components_by_key: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}

	for company_index, raw_company in enumerate(
		_expect_list(root.get("companies"), "catalog.companies", errors)
	):
		path = f"catalog.companies[{company_index}]"
		company = _expect_mapping(raw_company, path, errors)
		_reject_unknown(company, COMPANY_KEYS, path, errors)
		_require(company, COMPANY_KEYS, path, errors)
		company_id = _validate_id(company.get("id"), f"{path}.id", errors)
		label = _validate_nonempty_string(company.get("label"), f"{path}.label", errors)
		if company_id in companies_by_id:
			errors.append(f"{path}.id: duplicate company id {company_id!r}")
		if label in companies_by_label:
			errors.append(f"{path}.label: duplicate company label {label!r}")
		companies_by_id[company_id] = company
		companies_by_label[label] = company
		_validate_common_entity(company, path, owner_ids, errors)

		server_ids: set[str] = set()
		server_aliases: set[str] = set()
		for server_index, raw_server in enumerate(
			_expect_list(company.get("servers"), f"{path}.servers", errors)
		):
			server_path = f"{path}.servers[{server_index}]"
			server = _expect_mapping(raw_server, server_path, errors)
			_reject_unknown(server, SERVER_KEYS, server_path, errors)
			_require(server, SERVER_KEYS, server_path, errors)
			server_id = _validate_id(server.get("id"), f"{server_path}.id", errors)
			alias = _validate_nonempty_string(server.get("alias"), f"{server_path}.alias", errors)
			if server_id in server_ids:
				errors.append(f"{server_path}.id: duplicate server id {server_id!r}")
			if alias in server_aliases:
				errors.append(f"{server_path}.alias: duplicate server alias {alias!r}")
			server_ids.add(server_id)
			server_aliases.add(alias)
			_validate_nonempty_string(server.get("role"), f"{server_path}.role", errors)
			if server.get("status") not in ENTITY_STATUSES:
				errors.append(f"{server_path}.status: unsupported status {server.get('status')!r}")
			_validate_common_entity(server, server_path, owner_ids, errors)
			servers_by_key[(label, alias)] = server

			application_ids: set[str] = set()
			application_stacks: set[str] = set()
			for app_index, raw_application in enumerate(
				_expect_list(server.get("applications"), f"{server_path}.applications", errors)
			):
				app_path = f"{server_path}.applications[{app_index}]"
				application = _expect_mapping(raw_application, app_path, errors)
				_reject_unknown(application, APPLICATION_KEYS, app_path, errors)
				_require(application, APPLICATION_KEYS, app_path, errors)
				app_id = _validate_id(application.get("id"), f"{app_path}.id", errors)
				stack = _validate_nonempty_string(application.get("stack"), f"{app_path}.stack", errors)
				if app_id in application_ids:
					errors.append(f"{app_path}.id: duplicate application id {app_id!r}")
				if stack in application_stacks:
					errors.append(f"{app_path}.stack: duplicate stack {stack!r}")
				application_ids.add(app_id)
				application_stacks.add(stack)
				if application.get("status") not in ENTITY_STATUSES:
					errors.append(f"{app_path}.status: unsupported status {application.get('status')!r}")
				_validate_common_entity(application, app_path, owner_ids, errors)
				applications_by_key[(label, alias, stack)] = application

				component_ids: set[str] = set()
				component_services: set[str] = set()
				components = _expect_list(application.get("components"), f"{app_path}.components", errors)
				if application.get("status") == "active" and not components:
					errors.append(f"{app_path}.components: active application needs expected components")
				for component_index, raw_component in enumerate(components):
					component_path = f"{app_path}.components[{component_index}]"
					component = _expect_mapping(raw_component, component_path, errors)
					_reject_unknown(component, COMPONENT_KEYS, component_path, errors)
					_require(component, COMPONENT_KEYS, component_path, errors)
					component_id = _validate_id(component.get("id"), f"{component_path}.id", errors)
					service = _validate_nonempty_string(
						component.get("service"), f"{component_path}.service", errors
					)
					if component_id in component_ids:
						errors.append(f"{component_path}.id: duplicate component id {component_id!r}")
					if service in component_services:
						errors.append(f"{component_path}.service: duplicate service {service!r}")
					component_ids.add(component_id)
					component_services.add(service)
					_validate_bool(component.get("expected"), f"{component_path}.expected", errors)
					_validate_common_entity(component, component_path, owner_ids, errors)
					components_by_key[(label, alias, stack, service)] = component

	if set(company_values) != set(companies_by_label):
		errors.append(
			"catalog.labels.company_values: must exactly match canonical company labels"
		)

	seen_nodes: set[tuple[str, str]] = set()
	for index, raw_node in enumerate(_expect_list(root.get("nodes"), "catalog.nodes", errors)):
		path = f"catalog.nodes[{index}]"
		node = _expect_mapping(raw_node, path, errors)
		_reject_unknown(node, LEGACY_NODE_KEYS, path, errors)
		_require(node, ("alias", "company", "role"), path, errors)
		key = (str(node.get("company", "")), str(node.get("alias", "")))
		if key in seen_nodes:
			errors.append(f"{path}: duplicate legacy node {key!r}")
		seen_nodes.add(key)
		server = servers_by_key.get(key)
		if not server:
			errors.append(f"{path}: no canonical server for company/alias {key!r}")
		elif node.get("role") != server.get("role"):
			errors.append(f"{path}.role: differs from canonical server role")

	seen_urls: set[str] = set()
	for index, raw_service in enumerate(
		_expect_list(root.get("http_services"), "catalog.http_services", errors)
	):
		path = f"catalog.http_services[{index}]"
		service_entry = _expect_mapping(raw_service, path, errors)
		_reject_unknown(service_entry, HTTP_SERVICE_KEYS, path, errors)
		_require(
			service_entry,
			("company", "alias", "stack", "service", "url", "criticality"),
			path,
			errors,
		)
		url = _validate_nonempty_string(service_entry.get("url"), f"{path}.url", errors)
		parsed = urlsplit(url)
		if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
			errors.append(f"{path}.url: expected absolute HTTP(S) URL without credentials")
		if parsed.fragment:
			errors.append(f"{path}.url: fragments are not allowed")
		if url in seen_urls:
			errors.append(f"{path}.url: duplicate URL {url!r}")
		seen_urls.add(url)
		if service_entry.get("criticality") not in CRITICALITIES:
			errors.append(f"{path}.criticality: unsupported value {service_entry.get('criticality')!r}")
		monitoring = service_entry.get("monitoring", True)
		if not isinstance(monitoring, bool):
			monitoring_mapping = _expect_mapping(monitoring, f"{path}.monitoring", errors)
			_reject_unknown(monitoring_mapping, HTTP_MONITORING_KEYS, f"{path}.monitoring", errors)
			for key, value in monitoring_mapping.items():
				_validate_bool(value, f"{path}.monitoring.{key}", errors)
		key = (
			str(service_entry.get("company", "")),
			str(service_entry.get("alias", "")),
			str(service_entry.get("stack", "")),
			str(service_entry.get("service", "")),
		)
		component = components_by_key.get(key)
		if not component:
			errors.append(f"{path}: no canonical component for labels {key!r}")
		elif component.get("expected") is not True:
			errors.append(f"{path}: mapped canonical component is not expected")

	for index, raw_pending in enumerate(
		_expect_list(root.get("pending_discovery"), "catalog.pending_discovery", errors)
	):
		path = f"catalog.pending_discovery[{index}]"
		pending = _expect_mapping(raw_pending, path, errors)
		_reject_unknown(pending, PENDING_DISCOVERY_KEYS, path, errors)
		_require(pending, PENDING_DISCOVERY_KEYS, path, errors)
		company = str(pending.get("company", ""))
		alias = str(pending.get("alias", ""))
		if (company, alias) not in servers_by_key:
			errors.append(f"{path}: no canonical server for company/alias {(company, alias)!r}")
		stacks = _expect_list(pending.get("stacks"), f"{path}.stacks", errors)
		if len(stacks) != len(set(stacks)):
			errors.append(f"{path}.stacks: duplicate values")
		for stack_index, stack in enumerate(stacks):
			application = applications_by_key.get((company, alias, str(stack)))
			if not application:
				errors.append(f"{path}.stacks[{stack_index}]: no canonical application for {stack!r}")
			elif application.get("status") != "pending_discovery":
				errors.append(f"{path}.stacks[{stack_index}]: canonical application is not pending_discovery")

	event_defaults = _expect_mapping(
		root.get("service_event_defaults"), "catalog.service_event_defaults", errors
	)
	_reject_unknown(event_defaults, SERVICE_EVENT_TYPES, "catalog.service_event_defaults", errors)
	for event_type in sorted(SERVICE_EVENT_TYPES):
		path = f"catalog.service_event_defaults.{event_type}"
		if event_type not in event_defaults:
			errors.append(f"catalog.service_event_defaults: missing {event_type!r}")
			continue
		policy = _expect_mapping(event_defaults[event_type], path, errors)
		_reject_unknown(policy, EVENT_DEFAULT_KEYS, path, errors)
		_require(policy, EVENT_DEFAULT_KEYS, path, errors)
		_validate_lead_days(policy.get("admin_lead_days"), f"{path}.admin_lead_days", errors)
		_validate_lead_days(policy.get("customer_lead_days"), f"{path}.customer_lead_days", errors)

	seen_event_ids: set[str] = set()
	for index, raw_event in enumerate(
		_expect_list(root.get("service_events"), "catalog.service_events", errors)
	):
		path = f"catalog.service_events[{index}]"
		event = _expect_mapping(raw_event, path, errors)
		_reject_unknown(event, SERVICE_EVENT_KEYS, path, errors)
		_require(
			event,
			(
				"id",
				"type",
				"title",
				"company",
				"server",
				"due_at",
				"status",
				"owners",
				"customer_visible",
				"repository",
				"runbook",
			),
			path,
			errors,
		)
		event_id = _validate_id(event.get("id"), f"{path}.id", errors)
		if event_id in seen_event_ids:
			errors.append(f"{path}.id: duplicate service event id {event_id!r}")
		seen_event_ids.add(event_id)
		if event.get("type") not in SERVICE_EVENT_TYPES:
			errors.append(f"{path}.type: unsupported type {event.get('type')!r}")
		_validate_nonempty_string(event.get("title"), f"{path}.title", errors)
		company_id = str(event.get("company", ""))
		company = companies_by_id.get(company_id)
		if not company:
			errors.append(f"{path}.company: unknown canonical company id {company_id!r}")
			company_label = ""
		else:
			company_label = str(company.get("label", ""))
		server_id = str(event.get("server", ""))
		server = None
		if company:
			server = next((item for item in company.get("servers", []) if item.get("id") == server_id), None)
		if not server:
			errors.append(f"{path}.server: unknown server id {server_id!r}")
		application_id = event.get("application")
		application = None
		if application_id is not None:
			if not isinstance(application_id, str):
				errors.append(f"{path}.application: expected canonical application id")
			elif server:
				application = next(
					(item for item in server.get("applications", []) if item.get("id") == application_id),
					None,
				)
				if not application:
					errors.append(f"{path}.application: unknown application id {application_id!r}")
		component_id = event.get("component")
		if component_id is not None:
			if not isinstance(component_id, str) or not application:
				errors.append(f"{path}.component: requires a valid application")
			elif not any(item.get("id") == component_id for item in application.get("components", [])):
				errors.append(f"{path}.component: unknown component id {component_id!r}")
		try:
			due_at = parse_due_at(event.get("due_at"))
		except ValueError as exc:
			errors.append(f"{path}.due_at: {exc}")
			due_at = None
		status = event.get("status")
		if status not in SERVICE_EVENT_STATUSES:
			errors.append(f"{path}.status: unsupported status {status!r}")
		if due_at is None and status != "date_unknown":
			errors.append(f"{path}: missing due_at requires status 'date_unknown'")
		if due_at is not None and status == "date_unknown":
			errors.append(f"{path}: known due_at cannot use status 'date_unknown'")
		_validate_owner_refs(event.get("owners"), f"{path}.owners", owner_ids, errors)
		_validate_bool(event.get("customer_visible"), f"{path}.customer_visible", errors)
		_validate_optional_string(event.get("repository"), f"{path}.repository", errors)
		_validate_optional_string(event.get("runbook"), f"{path}.runbook", errors)
		if "notes" in event:
			_validate_optional_string(event.get("notes"), f"{path}.notes", errors)

	return errors


def load_catalog(path: str | Path) -> dict[str, Any]:
	"""Load YAML, validate it strictly, and return the catalog mapping."""

	catalog_path = Path(path)
	try:
		with catalog_path.open("r", encoding="utf-8") as handle:
			catalog = yaml.safe_load(handle)
	except (OSError, yaml.YAMLError) as exc:
		raise CatalogValidationError((f"{catalog_path}: cannot load catalog: {exc}",)) from exc
	errors = validate_catalog(catalog)
	if errors:
		raise CatalogValidationError(errors)
	return dict(catalog)


def http_monitoring_enabled(item: Mapping[str, Any], signal: str) -> bool:
	"""Return whether a legacy HTTP service enables a particular signal."""

	monitoring = item.get("monitoring", True)
	if isinstance(monitoring, bool):
		return monitoring
	if not monitoring.get("enabled", True):
		return False
	return bool(monitoring.get(signal, True))


def iter_http_services(catalog: Mapping[str, Any], signal: str) -> Iterable[Mapping[str, Any]]:
	for item in catalog.get("http_services", []):
		if http_monitoring_enabled(item, signal):
			yield item
