export const ANTIGRAVITY_MENU_COMMAND = "antigravity", ANTIGRAVITY_MENU_TITLE = "Antigravity", MENU_SECTION_SLOTS = [
  "accounts",
  "quota",
  "routing",
  "limits",
  "cache",
  "diagnostics",
  "extra"
];
const FORBIDDEN_FACT_NAME = /email|token|secret|password|credential|cookie|bearer|refresh|access|project|fingerprint|apikey|api_key/i, EMAIL_SHAPE = /[^\s@]+@[^\s@]+\.[^\s@]+/, ORDINAL_LABEL = /^Account [1-9][0-9]{0,5}$/;
function isRecord(value) {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return !1;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}
function onlyKeys(record, allowed, path, issues) {
  for (const key of Object.keys(record))
    if (!allowed.includes(key))
      issues.push(`${path}.${key}: unexpected field`);
}
function str(value, path, issues, optional = !1) {
  if (value === void 0 && optional)
    return !0;
  if (typeof value !== "string") {
    issues.push(`${path}: expected text`);
    return !1;
  }
  if (EMAIL_SHAPE.test(value)) {
    issues.push(`${path}: carries an email address`);
    return !1;
  }
  return !0;
}
function id(value, path, issues) {
  if (typeof value !== "string" || value.length === 0)
    issues.push(`${path}: expected a non-empty id`);
}
function facts(value, path, issues) {
  if (value === void 0)
    return;
  if (!isRecord(value)) {
    issues.push(`${path}: expected name/value pairs`);
    return;
  }
  for (const [name, entry] of Object.entries(value)) {
    if (FORBIDDEN_FACT_NAME.test(name)) {
      issues.push(`${path}.${name}: credential-shaped field`);
      continue;
    }
    if (typeof entry === "string") {
      str(entry, `${path}.${name}`, issues);
      continue;
    }
    if (entry !== null && typeof entry !== "boolean" && !(typeof entry === "number" && Number.isFinite(entry)))
      issues.push(`${path}.${name}: expected a plain value`);
  }
}
function knob(value, path, issues) {
  if (!isRecord(value)) {
    issues.push(`${path}: expected an input`);
    return;
  }
  id(value.id, `${path}.id`, issues);
  str(value.label, `${path}.label`, issues);
  switch (value.kind) {
    case "choice":
      onlyKeys(value, ["kind", "id", "label", "choices", "value"], path, issues);
      if (!Array.isArray(value.choices))
        issues.push(`${path}.choices: expected a list`);
      else
        value.choices.forEach((choice, index) => {
          const at = `${path}.choices.${index}`;
          if (!isRecord(choice)) {
            issues.push(`${at}: expected a choice`);
            return;
          }
          onlyKeys(choice, ["value", "label"], at, issues);
          str(choice.value, `${at}.value`, issues);
          str(choice.label, `${at}.label`, issues);
        });
      str(value.value, `${path}.value`, issues, !0);
      return;
    case "toggle":
      onlyKeys(value, ["kind", "id", "label", "value"], path, issues);
      if (typeof value.value !== "boolean")
        issues.push(`${path}.value: expected on/off`);
      return;
    case "number":
      onlyKeys(value, ["kind", "id", "label", "value", "min", "max", "required"], path, issues);
      for (const key of ["value", "min", "max"]) {
        const entry = value[key];
        if (entry !== void 0 && !(typeof entry === "number" && Number.isFinite(entry)))
          issues.push(`${path}.${key}: expected a number`);
      }
      return;
    case "text":
      onlyKeys(value, ["kind", "id", "label", "value", "placeholder", "masked", "required"], path, issues);
      str(value.value, `${path}.value`, issues, !0);
      str(value.placeholder, `${path}.placeholder`, issues, !0);
      return;
    default:
      issues.push(`${path}.kind: unknown input kind`);
  }
}
function action(value, path, issues) {
  if (!isRecord(value)) {
    issues.push(`${path}: expected an action`);
    return;
  }
  onlyKeys(value, ["id", "label", "description", "group", "knobs", "confirm"], path, issues);
  id(value.id, `${path}.id`, issues);
  str(value.label, `${path}.label`, issues);
  str(value.description, `${path}.description`, issues, !0);
  str(value.group, `${path}.group`, issues, !0);
  if (!Array.isArray(value.knobs))
    issues.push(`${path}.knobs: expected a list`);
  else
    value.knobs.forEach((entry, index) => {
      knob(entry, `${path}.knobs.${index}`, issues);
    });
  if (value.confirm !== void 0) {
    const confirm = value.confirm;
    if (!isRecord(confirm))
      issues.push(`${path}.confirm: expected a confirmation`);
    else {
      onlyKeys(confirm, ["message", "irreversible"], `${path}.confirm`, issues);
      str(confirm.message, `${path}.confirm.message`, issues);
      if (typeof confirm.irreversible !== "boolean")
        issues.push(`${path}.confirm.irreversible: expected true/false`);
    }
  }
}
function actions(value, path, issues) {
  if (!Array.isArray(value)) {
    issues.push(`${path}: expected a list`);
    return;
  }
  value.forEach((entry, index) => {
    action(entry, `${path}.${index}`, issues);
  });
}
function account(value, path, issues) {
  if (value === void 0)
    return;
  if (!isRecord(value)) {
    issues.push(`${path}: expected an account`);
    return;
  }
  onlyKeys(value, ["id", "label", "enabled", "type"], path, issues);
  id(value.id, `${path}.id`, issues);
  if (value.label !== void 0 && (typeof value.label !== "string" || !ORDINAL_LABEL.test(value.label)))
    issues.push(`${path}.label: expected an ordinal account label`);
  if (typeof value.enabled !== "boolean")
    issues.push(`${path}.enabled: expected true/false`);
  if (value.type !== "oauth" && value.type !== "api")
    issues.push(`${path}.type: unknown account type`);
}
function item(value, path, issues) {
  if (!isRecord(value)) {
    issues.push(`${path}: expected an item`);
    return;
  }
  onlyKeys(value, ["id", "label", "detail", "group", "status", "account", "facts", "actions"], path, issues);
  id(value.id, `${path}.id`, issues);
  str(value.label, `${path}.label`, issues);
  str(value.detail, `${path}.detail`, issues, !0);
  str(value.group, `${path}.group`, issues, !0);
  str(value.status, `${path}.status`, issues, !0);
  account(value.account, `${path}.account`, issues);
  facts(value.facts, `${path}.facts`, issues);
  actions(value.actions, `${path}.actions`, issues);
}
function section(value, path, issues) {
  if (!isRecord(value)) {
    issues.push(`${path}: expected a section`);
    return;
  }
  onlyKeys(value, ["id", "slot", "title", "lines", "items", "actions", "facts"], path, issues);
  id(value.id, `${path}.id`, issues);
  if (!MENU_SECTION_SLOTS.includes(value.slot))
    issues.push(`${path}.slot: unknown section slot`);
  str(value.title, `${path}.title`, issues);
  if (!Array.isArray(value.lines))
    issues.push(`${path}.lines: expected a list`);
  else
    value.lines.forEach((line, index) => {
      str(line, `${path}.lines.${index}`, issues);
    });
  if (!Array.isArray(value.items))
    issues.push(`${path}.items: expected a list`);
  else
    value.items.forEach((entry, index) => {
      item(entry, `${path}.items.${index}`, issues);
    });
  actions(value.actions, `${path}.actions`, issues);
  facts(value.facts, `${path}.facts`, issues);
}
function menu(value, path, issues) {
  if (!isRecord(value)) {
    issues.push(`${path}: expected a menu`);
    return;
  }
  onlyKeys(value, ["command", "title", "sections"], path, issues);
  if (value.command !== ANTIGRAVITY_MENU_COMMAND)
    issues.push(`${path}.command: not the ${ANTIGRAVITY_MENU_COMMAND} menu`);
  str(value.title, `${path}.title`, issues);
  if (!Array.isArray(value.sections)) {
    issues.push(`${path}.sections: expected a list`);
    return;
  }
  let lastSlot = -1;
  value.sections.forEach((entry, index) => {
    section(entry, `${path}.sections.${index}`, issues);
    const slot = isRecord(entry) ? MENU_SECTION_SLOTS.indexOf(entry.slot) : -1;
    if (slot >= 0 && slot < lastSlot)
      issues.push(`${path}.sections.${index}.slot: out of the fixed order`);
    lastSlot = Math.max(lastSlot, slot);
  });
}
function finish(value, issues) {
  return issues.length === 0 ? { ok: !0, value } : { ok: !1, issues };
}
export function parseMenuDialogPayload(value) {
  const issues = [];
  if (!isRecord(value))
    return { ok: !1, issues: ["payload: expected an object"] };
  onlyKeys(value, ["command", "menu"], "payload", issues);
  if (value.command !== ANTIGRAVITY_MENU_COMMAND)
    issues.push("payload.command: not the antigravity menu");
  menu(value.menu, "payload.menu", issues);
  return finish(value, issues);
}
export function parseMenuNotifyPayload(value) {
  const issues = [];
  if (!isRecord(value))
    return { ok: !1, issues: ["payload: expected an object"] };
  onlyKeys(value, ["command", "notify"], "payload", issues);
  if (value.command !== ANTIGRAVITY_MENU_COMMAND)
    issues.push("payload.command: not the antigravity menu");
  const notify = value.notify;
  if (!isRecord(notify))
    issues.push("payload.notify: expected a message");
  else {
    onlyKeys(notify, ["message", "kind"], "payload.notify", issues);
    str(notify.message, "payload.notify.message", issues);
    if (notify.kind !== "info" && notify.kind !== "warning" && notify.kind !== "error")
      issues.push("payload.notify.kind: unknown kind");
  }
  return finish(value, issues);
}
export function parseMenuApplyResult(value) {
  const issues = [];
  if (!isRecord(value))
    return { ok: !1, issues: ["result: expected an object"] };
  onlyKeys(value, ["command", "ok", "text", "code", "needsConfirmation", "menu"], "result", issues);
  if (value.command !== ANTIGRAVITY_MENU_COMMAND)
    issues.push("result.command: not the antigravity menu");
  if (typeof value.ok !== "boolean")
    issues.push("result.ok: expected true/false");
  str(value.text, "result.text", issues);
  if (value.code !== void 0 && typeof value.code !== "string")
    issues.push("result.code: expected text");
  if (value.needsConfirmation !== void 0 && typeof value.needsConfirmation !== "boolean")
    issues.push("result.needsConfirmation: expected true/false");
  menu(value.menu, "result.menu", issues);
  return finish(value, issues);
}
export const MENU_REFUSED_TEXT = "Antigravity sent a menu this TUI does not understand; nothing was shown.";
