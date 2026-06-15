"""Parser for MobiFlight ``.mcc`` configuration files.

We only model the subset the IFR-1 / X-Plane configs use:
  * inputs  -> X-Plane Command actions and Variable (set var) actions,
               optionally gated by variable preconditions.
  * outputs -> X-Plane DataRef sources with a transform expression and a
               target LED "pin".
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class Precondition:
    ref: str            # variable name, e.g. "FMS1_RNG"
    operand: str        # "=", "<", ">", ...
    value: str          # compared value (string in the XML)
    logic: str = "and"  # "and" / "or"
    active: bool = True


@dataclass
class CommandAction:
    """Trigger an X-Plane command."""
    path: str


@dataclass
class VariableAction:
    """Set an internal MobiFlight variable."""
    var_name: str
    expression: str      # MobiFlight expression, usually a literal like "1"


Action = CommandAction | VariableAction


@dataclass
class InputConfig:
    guid: str
    active: bool
    description: str
    name: str                              # e.g. "Button_COM1_OI"
    on_press: Action | None = None
    on_release: Action | None = None
    preconditions: list[Precondition] = field(default_factory=list)


@dataclass
class OutputConfig:
    guid: str
    active: bool
    description: str
    dataref: str                           # X-Plane dataref path
    transform: str = "$"                   # expression, "$" == identity
    transform_active: bool = False
    pin: str = ""                          # LED pin name, e.g. "AP HDG"
    trigger: str = "normal"


def _text(el: ET.Element | None, default: str = "") -> str:
    return el.text if el is not None and el.text is not None else default


def _parse_action(el: ET.Element | None) -> Action | None:
    if el is None:
        return None
    a_type = el.get("type", "")
    if a_type == "XplaneInputAction":
        # inputType is usually "Command"; path holds the command/dataref.
        return CommandAction(path=el.get("path", ""))
    if a_type == "VariableInputAction":
        return VariableAction(
            var_name=el.get("varName", ""),
            expression=el.get("varExpression", ""),
        )
    return None  # unknown action type — caller logs/ignores


def _parse_preconditions(parent: ET.Element) -> list[Precondition]:
    out: list[Precondition] = []
    pcs = parent.find("preconditions")
    if pcs is None:
        return out
    for pc in pcs.findall("precondition"):
        if pc.get("type") != "variable":
            continue
        out.append(Precondition(
            ref=pc.get("ref", ""),
            operand=pc.get("operand", "="),
            value=pc.get("value", ""),
            logic=pc.get("logic", "and"),
            active=pc.get("active", "true").lower() == "true",
        ))
    return out


def _parse_input(config: ET.Element) -> InputConfig | None:
    settings = config.find("settings")
    if settings is None:
        return None
    button = settings.find("button")
    on_press = on_release = None
    if button is not None:
        on_press = _parse_action(button.find("onPress"))
        on_release = _parse_action(button.find("onRelease"))
    return InputConfig(
        guid=config.get("guid", ""),
        active=_text(config.find("active"), "false").lower() == "true",
        description=_text(config.find("description")),
        name=settings.get("name", ""),
        on_press=on_press,
        on_release=on_release,
        preconditions=_parse_preconditions(settings),
    )


def _parse_output(config: ET.Element) -> OutputConfig | None:
    settings = config.find("settings")
    if settings is None:
        return None
    source = settings.find("source")
    display = settings.find("display")
    transform = "$"
    transform_active = False
    mods = settings.find("modifiers")
    if mods is not None:
        tr = mods.find("transformation")
        if tr is not None:
            transform = tr.get("expression", "$")
            transform_active = tr.get("active", "False").lower() == "true"
    return OutputConfig(
        guid=config.get("guid", ""),
        active=_text(config.find("active"), "false").lower() == "true",
        description=_text(config.find("description")),
        dataref=source.get("path", "") if source is not None else "",
        transform=transform,
        transform_active=transform_active,
        pin=display.get("pin", "") if display is not None else "",
        trigger=display.get("trigger", "normal") if display is not None else "normal",
    )


@dataclass
class MccConfig:
    inputs: list[InputConfig]
    outputs: list[OutputConfig]

    def inputs_by_name(self) -> dict[str, list[InputConfig]]:
        """Group active inputs by their MobiFlight name.

        Several configs can share a name and differ only by precondition
        (e.g. FMS1 encoder: one binding for RNG=0, one for RNG=1).
        """
        out: dict[str, list[InputConfig]] = {}
        for cfg in self.inputs:
            if cfg.active and cfg.name:
                out.setdefault(cfg.name, []).append(cfg)
        return out


def parse_mcc(path: str) -> MccConfig:
    # The file is UTF-8 with a BOM; ET handles that fine.
    tree = ET.parse(path)
    root = tree.getroot()

    inputs: list[InputConfig] = []
    outputs: list[OutputConfig] = []

    out_root = root.find("outputs")
    if out_root is not None:
        for config in out_root.findall("config"):
            oc = _parse_output(config)
            if oc is not None:
                outputs.append(oc)

    in_root = root.find("inputs")
    if in_root is not None:
        for config in in_root.findall("config"):
            ic = _parse_input(config)
            if ic is not None:
                inputs.append(ic)

    return MccConfig(inputs=inputs, outputs=outputs)
