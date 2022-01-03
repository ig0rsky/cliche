__project__ = "cliche"
__version__ = "0.7.63"
import time
import sys

if not getattr(sys, "cliche_ts__", False):
    sys.cliche_ts__ = 0

import re
import os
import code
import json
from inspect import signature, currentframe, getmro
import traceback
from typing import List, Iterable, Set, Tuple, Union
from types import ModuleType

CLICHE_INIT_TS = time.time()

try:
    import argcomplete

    ARGCOMPLETE_IMPORTED = True
except ImportError:
    ARGCOMPLETE_IMPORTED = False

from cliche.using_underscore import UNDERSCORE_DETECTED
from cliche.install import install, uninstall
from cliche.choice import Choice, Enum
from cliche.argparser import (
    ColoredHelpOnErrorParser,
    pydantic_models,
    add_arguments_to_command,
    add_command,
    get_var_name_and_default,
    bool_inverted,
    container_fn_name_to_type,
    class_init_lookup,
)

CLICHE_AFTER_INIT_TS = time.time()
loaded_modules_before = set(sys.modules)


def get_class(f):
    vals = vars(sys.modules[f.__module__])
    for attr in f.__qualname__.split(".")[:-1]:
        try:
            vals = vals[attr]
        except TypeError:
            return None
    if isinstance(vals, dict):
        return None
    return vals


def get_init(f):
    cl = get_class(f)
    if cl is None:
        return None, None
    for init_class in cl.__mro__:
        init = getattr(init_class, "__init__")
        if init is not None:
            return init_class, init


def highlight(x):
    return "\x1b[1;36m{}\x1b[0m".format(x)


def cli_info(**kwargs):
    """Outputs CLI and Python version info and exits."""
    sv = sys.version_info
    python_version = "{}.{}.{}".format(sv.major, sv.minor, sv.micro)
    installed = False
    try:
        with open(sys.argv[0]) as f:
            txt = f.read()
            installed = "__import__(function_to_imports[command])" in txt
            file_path = re.findall('file_path = "(.+)"', txt)
    except FileNotFoundError:
        pass
    autocomplete = False
    try:
        name = os.path.basename(sys.argv[0])
        with open(os.path.expanduser("~/.bashrc")) as f:
            autocomplete = f"register-python-argcomplete {name}" in f.read()
    except FileNotFoundError:
        pass
    v = f" (version {version[0]})" if version else ""
    print("Executable:          ", highlight(name + v))
    print("Executable path:     ", highlight(sys.argv[0]))
    print("Cliche version:      ", highlight(__version__))
    print("Installed by cliche: ", highlight(installed))
    if installed:
        print("CLI directory:       ", highlight(file_path[0]))
    print("Autocomplete enabled:", highlight(autocomplete), "(only possible on Linux)")
    print("Python Version:      ", highlight(python_version))
    print("Python Interpreter:  ", highlight(sys.executable))


# t1 = time.time()

fn_registry = {}
fn_class_registry = {}
main_called = []
version = []
use_timing = False
if "--cli" in sys.argv:
    cli_info()
    sys.exit(0)

if "--timing" in sys.argv:
    sys.argv.remove("--timing")
    use_timing = True
    print(
        "timing cliche modules loading",
        CLICHE_AFTER_INIT_TS - CLICHE_INIT_TS,
    )
    print("diff inits", CLICHE_AFTER_INIT_TS - sys.cliche_ts__)


def warn(x):
    sys.stderr.write("\033[31m" + x + "\033[0m\n")
    sys.stderr.flush()


def cli(fn):
    # print(fn, time.time() - t1) # for debug
    current_modules = set(sys.modules)
    new_modules = current_modules - loaded_modules_before
    loaded_modules_before.update(current_modules)
    t1 = time.time()
    module = sys.modules[fn.__module__]
    fn.lookup = {}

    for x in dir(module):
        if x.startswith("_"):
            continue
        item = getattr(module, x)
        if isinstance(item, ModuleType):
            sub_module = item
            for y in dir(sub_module):
                fn.lookup[(x, y)] = getattr(sub_module, y)
                fn.lookup[(x, y + "Value")] = getattr(sub_module, y)
        else:
            fn.lookup[(x,)] = getattr(module, x)
            fn.lookup[(x + "Value",)] = getattr(module, x)
            fn.lookup[(x, "V")] = getattr(module, x)
        if "." in fn.__qualname__:
            class_init_lookup[".".join(fn.__qualname__.split(".")[:-1]) + ".__init__"] = fn.lookup

    def decorated_fn(*args, **kwargs):
        no_traceback = False
        raw = False
        if "notraceback" in kwargs:
            no_traceback = kwargs.pop("notraceback")
        if "raw" in kwargs:
            raw = kwargs.pop("raw")
        if "cli" in kwargs:
            kwargs.pop("cli")
        if "pdb" in kwargs:
            kwargs.pop("pdb")
        if "timing" in kwargs:
            kwargs.pop("timing")
        try:
            if not UNDERSCORE_DETECTED:
                kwargs = {k.replace("-", "_"): v for k, v in kwargs.items()}
            if fn in pydantic_models:
                for var_name in pydantic_models[fn]:
                    model, model_args = pydantic_models[fn][var_name]
                    for m in model_args:
                        kwargs.pop(m)
                    kwargs[var_name] = model(**kwargs)
            fn_time = time.time()
            res = fn(*args, **kwargs)
            if use_timing:
                print("timing fuction call success", time.time() - fn_time)
            if res is not None:
                if raw:
                    print(res)
                else:
                    try:
                        print(json.dumps(res, indent=4))
                    except json.JSONDecodeError:
                        print(res)
        except Exception as e:
            if use_timing:
                print("timing fuction call success", time.time() - fn_time)
            fname, sig = fn.__name__, signature(fn)
            print("Fault while calling {}{} with the above arguments".format(fname, sig))
            if no_traceback:
                warn(traceback.format_exception_only(type(e), e)[-1].strip().split(" ", 1)[1])
                sys.exit(1)
            else:
                raise

    if UNDERSCORE_DETECTED:
        fn_registry[fn.__name__] = (decorated_fn, fn)
    else:
        fn_registry[fn.__name__.replace("_", "-")] = (decorated_fn, fn)
    if use_timing:
        new_m = len(new_modules)
        if new_m > 5:
            new_module_text = f"({new_m} new_modules since last cli decoration)"
        elif not new_modules:
            new_module_text = "(no new modules loaded)"
        else:
            new_module_text = f"(loaded {', '.join(new_modules)} module(s) since last cli decoration)"
        print(
            "timing preparing",
            fn.__name__,
            time.time() - t1,
            "since startup",
            time.time() - CLICHE_INIT_TS,
            new_module_text,
        )
    return fn


def add_traceback(parser):
    parser.add_argument(
        "--notraceback",
        action="store_true",
        default=False,
        help="Omit showing Python tracebacks",
    )


def add_pdb(parser):
    if [x for x in parser._actions if "--pdb" in x.option_strings]:
        return
    parser.add_argument(
        "--pdb",
        action="store_true",
        default=False,
        help="Drop into pdb on error",
    )


def add_timing(parser):
    if [x for x in parser._actions if "--timing" in x.option_strings]:
        return
    parser.add_argument(
        "--timing",
        action="store_true",
        default=False,
        help="Add timings of cliche and function call",
    )


def add_raw(parser):
    parser.add_argument(
        "--raw",
        action="store_true",
        default=False,
        help="Prevent function output as JSON",
    )


def add_cli(parser):
    parser.add_argument(
        "--cli",
        action="store_true",
        default=False,
        help=cli_info.__doc__,
    )


def add_cliche_self_parser(parser):
    subparsers = parser.add_subparsers(dest="command")
    installer = subparsers.add_parser("install", help="Create CLI from current folder")
    installer.add_argument("name", help="Name of the cli to create")
    installer.add_argument(
        "-n",
        "--no-autocomplete",
        action="store_false",
        help="Default: False | Whether to add autocomplete support",
    )
    add_cli(parser)
    add_pdb(parser)
    add_timing(parser)
    bool_inverted.add("no_autocomplete")
    fn_registry["install"] = [install, install]
    uninstaller = subparsers.add_parser("uninstall", help="Delete CLI")
    uninstaller.add_argument("name", help="Name of the CLI to remove")
    fn_registry["uninstall"] = [uninstall, uninstall]


def add_class_arguments(cmd, fn, fn_name):
    abbrevs = None
    init_class, init = get_init(fn)
    if init is not None:
        group_name = "INITIALIZE CLASS: {}()".format(init.__qualname__.split(".")[0])
        group = cmd.add_argument_group(group_name)
        var_names = [x for x in init.__code__.co_varnames if x not in ["self", "cls"]]
        fn_class_registry[fn_name] = (init_class, var_names)
        abbrevs = add_arguments_to_command(group, init, abbrevs)
    return abbrevs


def add_optional_cliche_arguments(cmd):
    group = cmd.add_argument_group("OPTIONAL CLI ARGUMENTS")
    add_traceback(group)
    add_cli(group)
    add_pdb(group)
    add_timing(group)
    add_raw(group)


def get_parser():
    frame = currentframe().f_back
    module_doc = frame.f_code.co_consts[0]
    module_doc = module_doc if isinstance(module_doc, str) else None
    parser = ColoredHelpOnErrorParser(description=module_doc)

    from cliche import fn_registry

    if fn_registry:
        add_optional_cliche_arguments(parser)
        # if only one @cli and the second arg is not a command
        if len(fn_registry) == 1 and (len(sys.argv) < 2 or sys.argv[1] not in fn_registry):
            fn = list(fn_registry.values())[0][1]
            add_arguments_to_command(parser, fn)
        else:
            subparsers = parser.add_subparsers(dest="command")
            for fn_name, (decorated_fn, fn) in sorted(fn_registry.items(), key=lambda x: (x[0] == "info", x[0])):
                cmd = add_command(subparsers, fn_name, fn)

                # for methods defined on classes, add those args
                abbrevs = add_class_arguments(cmd, fn, fn_name)

                add_arguments_to_command(cmd, fn, abbrevs)

    else:
        add_cliche_self_parser(parser)

    return parser


def main(exclude_module_names=None, version_info=None, *parser_args):
    t1 = time.time()
    if main_called:
        return
    main_called.append(True)
    # if "cliche" in sys.argv[0] and "cliche/" not in sys.argv[0]:
    #     module_name = sys.argv[1]
    #     sys.argv.remove(module_name)
    #     import importlib.util

    #     spec = importlib.util.spec_from_file_location("pydantic", module_name)
    #     module = importlib.util.module_from_spec(spec)
    #     spec.loader.exec_module(module)
    #     ColoredHelpOnErrorParser.module_name = module_name

    if exclude_module_names is not None:
        # exclude module namespaces
        for x in exclude_module_names:
            for k, v in list(fn_registry.items()):
                _, fn = v
                if x in fn.__module__:
                    fn_registry.pop(k)

    if version_info is not None:
        version.append(version_info)

    use_pdb = False
    if "--pdb" in sys.argv:
        sys.argv.remove("--pdb")
        use_pdb = True

    parser = get_parser()

    if ARGCOMPLETE_IMPORTED:
        argcomplete.autocomplete(parser)

    if parser_args:
        parsed_args = parser.parse_args(parser_args)
    else:
        parsed_args = parser.parse_args()

    if use_timing:
        print("timing arg parsing", time.time() - t1)

    cmd = None
    try:
        cmd = parsed_args.command
    except AttributeError:
        if len(fn_registry) == 1:
            cmd = list(fn_registry)[0]
        else:
            warn("No commands have been registered.\n")
            parser.print_help()
            sys.exit(3)
    kwargs = dict(parsed_args._get_kwargs())
    if "command" in kwargs:
        kwargs.pop("command")
    for x in bool_inverted:
        if x in kwargs:
            # stripping "no-" from e.g. "--no-sums"
            kwargs[x[3:]] = kwargs.pop(x)
    if cmd is None:
        t2 = time.time()
        parser.print_help()
        if use_timing:
            print("timing print help", time.time() - t2)
    else:
        try:
            t3 = time.time()
            # test.... i think this is never filled, so lets try always with empty
            # starargs = parsed_args._get_args()
            starargs = []
            if cmd in fn_class_registry:
                init_class, init_varnames = fn_class_registry[cmd]
                init_kwargs = {k: kwargs.pop(k) for k in init_varnames if k in kwargs}
                # [k for k in init_varnames if k not in init_kwargs]
                fn_registry[cmd][0](init_class(**init_kwargs), **kwargs)
            else:
                for name, value in list(kwargs.items()):
                    for key in [(cmd, name), (cmd, "--" + name)]:
                        if key in container_fn_name_to_type:
                            if value is not None:
                                kwargs[name] = container_fn_name_to_type[key](value)
                fn_registry[cmd][0](*starargs, **kwargs)
                if use_timing:
                    print("timing fuction call success", time.time() - t3)
        except:
            if not use_pdb:
                if use_timing:
                    print("timing fuction call exception", time.time() - t3)
                raise
            import pdb

            extype, value, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
