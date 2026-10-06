"""Small reflection helpers to reach non-public members of the C# core.

White-box tests use these to drive private state machines directly (e.g. feed a
line into ``ManageReceivedLine``) instead of going through threads and timers.
"""

from __future__ import annotations

import clr  # noqa: F401  (pythonnet must be loaded by runtime.load() first)
import System
from System.Reflection import BindingFlags

ALL = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.FlattenHierarchy
INST = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance
STAT = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static


def type_name(obj) -> str:
    """Runtime type name of a CLR object (pythonnet may wrap it as its declared interface)."""
    return str(obj.GetType().Name)


def clr_type(obj_or_type) -> System.Type:
    if isinstance(obj_or_type, System.Type):
        return obj_or_type
    try:
        return clr.GetClrType(obj_or_type)
    except TypeError:
        return obj_or_type.GetType()


def _find_field(t: System.Type, name: str, flags):
    while t is not None:
        f = t.GetField(name, flags)
        if f is not None:
            return f
        t = t.BaseType
    raise AttributeError(name)


def _find_prop(t: System.Type, name: str, flags):
    while t is not None:
        p = t.GetProperty(name, flags | BindingFlags.DeclaredOnly)
        if p is not None:
            return p
        t = t.BaseType
    raise AttributeError(name)


def get(obj, name: str):
    """Read an instance field or property (any visibility, inherited too)."""
    t = obj.GetType()
    try:
        return _find_field(t, name, INST).GetValue(obj)
    except AttributeError:
        return _find_prop(t, name, INST).GetValue(obj, None)


def set(obj, name: str, value) -> None:  # noqa: A001
    t = obj.GetType()
    try:
        f = _find_field(t, name, INST)
        f.SetValue(obj, _coerce(value, f.FieldType))
    except AttributeError:
        p = _find_prop(t, name, INST)
        p.SetValue(obj, _coerce(value, p.PropertyType), None)


def sget(cls, name: str):
    t = clr_type(cls)
    try:
        return _find_field(t, name, STAT).GetValue(None)
    except AttributeError:
        return _find_prop(t, name, STAT).GetValue(None, None)


def sset(cls, name: str, value) -> None:
    t = clr_type(cls)
    try:
        f = _find_field(t, name, STAT)
        f.SetValue(None, _coerce(value, f.FieldType))
    except AttributeError:
        p = _find_prop(t, name, STAT)
        p.SetValue(None, _coerce(value, p.PropertyType), None)


def _methods(t: System.Type, name: str, flags):
    seen = []
    while t is not None:
        for m in t.GetMethods(flags | BindingFlags.DeclaredOnly):
            if m.Name == name:
                seen.append(m)
        if seen:
            return seen
        t = t.BaseType
    raise AttributeError(name)


def _pick(methods, args, types):
    if types is not None:
        for m in methods:
            ps = [p.ParameterType for p in m.GetParameters()]
            if len(ps) == len(types) and all(str(a.FullName) == str(clr_type(b).FullName) for a, b in zip(ps, types)):
                return m
        raise TypeError(f"no overload of {methods[0].Name} with types {types}")
    cands = [m for m in methods if len(m.GetParameters()) == len(args)]
    if len(cands) != 1:
        raise TypeError(f"ambiguous/no overload of {methods[0].Name} for {len(args)} args; pass types=")
    return cands[0]


def call(obj, name: str, *args, types=None):
    """Invoke an instance method of any visibility; unwraps TargetInvocationException."""
    m = _pick(_methods(obj.GetType(), name, INST), args, types)
    return _invoke(m, obj, args)


def scall(cls, name: str, *args, types=None):
    m = _pick(_methods(clr_type(cls), name, STAT), args, types)
    return _invoke(m, None, args)


_NUMERIC = {
    "System.Int32": System.Int32, "System.Int64": System.Int64, "System.Byte": System.Byte,
    "System.Single": System.Single, "System.Double": System.Double, "System.Decimal": System.Decimal,
    "System.UInt32": System.UInt32, "System.Int16": System.Int16,
}


def _coerce(value, ptype):
    """Python int/float -> the CLR numeric type the parameter expects (reflection does
    not convert boxed Python numbers)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    name = str(ptype.FullName)
    if ptype.IsEnum:
        return System.Enum.ToObject(ptype, value)
    conv = _NUMERIC.get(name)
    return conv(value) if conv is not None else value


def _invoke(m, target, args):
    params = list(m.GetParameters())
    args = [_coerce(a, p.ParameterType) for a, p in zip(args, params)] + list(args[len(params):])
    arr = System.Array[System.Object](list(args)) if args else None
    try:
        return m.Invoke(target, arr)
    except System.Reflection.TargetInvocationException as e:
        raise e.InnerException


def new(cls, *args, types=None):
    """Construct via a (possibly non-public) constructor."""
    t = clr_type(cls)
    ctors = list(t.GetConstructors(INST))
    if types is not None:
        cands = [
            c
            for c in ctors
            if len(c.GetParameters()) == len(types)
            and all(str(p.ParameterType.FullName) == str(clr_type(b).FullName) for p, b in zip(c.GetParameters(), types))
        ]
    else:
        cands = [c for c in ctors if len(c.GetParameters()) == len(args)]
    if len(cands) != 1:
        raise TypeError(f"no/ambiguous ctor of {t.Name} for {len(args)} args; pass types=")
    args = [_coerce(a, p.ParameterType) for a, p in zip(args, cands[0].GetParameters())]
    try:
        return cands[0].Invoke(System.Array[System.Object](list(args)))
    except System.Reflection.TargetInvocationException as e:
        raise e.InnerException


def nested(cls, name: str) -> System.Type:
    t = clr_type(cls).GetNestedType(name, BindingFlags.Public | BindingFlags.NonPublic)
    if t is None:
        raise AttributeError(name)
    return t


def enum_value(enum_type, name: str):
    return System.Enum.Parse(clr_type(enum_type), name)
