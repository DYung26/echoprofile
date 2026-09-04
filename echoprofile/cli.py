from __future__ import annotations

import argparse
import shutil
import sys

import httpx

from echoprofile.config import MAESTRO_PROFILE_DIR, load_config


def _connection_error(config) -> None:
    print(f"Could not reach echoprofile server at {config.base_url}.")
    print("Start it first with: echoprofile serve")
    sys.exit(1)


def _fail_on_error(response: httpx.Response, action: str) -> None:
    """Print the server's actual error detail and exit, instead of letting
    raise_for_status() surface a bare, undiagnosable 500 traceback.
    """
    if response.status_code < 400:
        return
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text
    print(f"{action} failed ({response.status_code}): {detail}")
    sys.exit(1)


def cmd_login(args: argparse.Namespace) -> None:
    """Ask the running `serve` process to open the persistent Edge profile,
    headed, and keep it open. Log in by hand directly in that window - it
    stays open across as many `clone` calls as you want; each one reads its
    current state fresh. Close it later with `echoprofile logout`.
    """
    config = load_config()
    load_switchboard = not args.no_switchboard
    print("Asking the server to open the persistent profile - this can take ")
    print("a while on a first/cold launch. Watch for a new browser window.")
    try:
        response = httpx.post(
            f"{config.base_url}/persistent/open",
            json={"load_switchboard": load_switchboard},
            timeout=120.0,
        )
    except httpx.ConnectError:
        _connection_error(config)
        return
    except httpx.ReadTimeout:
        print(
            "No response from the server after 120s. Check the `serve` "
            "terminal/log - if a browser window did open, it's still open "
            "and usable even though this command gave up waiting; run "
            "`echoprofile persistent-status` to confirm once it settles."
        )
        sys.exit(1)
    if response.status_code == 409:
        print("Persistent profile is already open.")
        return
    _fail_on_error(response, "Opening persistent profile")
    print(f"Persistent profile open at {config.profile_dir}")
    if load_switchboard:
        print("Switchboard extension loaded.")
    print("Log in as needed in that window. It stays open until `echoprofile logout`.")


def cmd_logout(_args: argparse.Namespace) -> None:
    config = load_config()
    try:
        response = httpx.post(f"{config.base_url}/persistent/close", timeout=30.0)
    except httpx.ConnectError:
        _connection_error(config)
        return
    if response.status_code == 409:
        print("Persistent profile is not open.")
        return
    _fail_on_error(response, "Closing persistent profile")
    print("Persistent profile closed.")


def cmd_persistent_status(_args: argparse.Namespace) -> None:
    config = load_config()
    try:
        response = httpx.get(f"{config.base_url}/persistent", timeout=10.0)
    except httpx.ConnectError:
        _connection_error(config)
        return
    _fail_on_error(response, "Checking persistent status")
    is_open = response.json()["open"]
    print("open" if is_open else "closed")


def cmd_seed_from_maestro(args: argparse.Namespace) -> None:
    """One-time filesystem copy of Maestro's persistent profile into this
    tool's own profile dir. A plain shutil.copytree, not a Playwright
    launch - never opens either profile, so it can't contend for a
    SingletonLock on Maestro's side or this tool's side.
    """
    config = load_config()
    source = MAESTRO_PROFILE_DIR
    if not source.exists():
        print(f"No Maestro profile found at {source}")
        sys.exit(1)

    lock_file = source / "SingletonLock"
    if lock_file.exists() and not args.force:
        print(f"Maestro's profile at {source} looks like it's currently open (SingletonLock present).")
        print("Close Maestro's browser session first, or re-run with --force to copy anyway.")
        sys.exit(1)

    if config.profile_dir.exists():
        if not args.force:
            print(f"{config.profile_dir} already exists. Re-run with --force to overwrite it.")
            sys.exit(1)
        shutil.rmtree(config.profile_dir)

    print(f"Copying {source} -> {config.profile_dir} ...")
    shutil.copytree(source, config.profile_dir, symlinks=True, ignore=shutil.ignore_patterns("SingletonLock", "SingletonCookie", "SingletonSocket"))
    print("Done. echoprofile now has its own independent copy of the login state.")


def cmd_serve(_args: argparse.Namespace) -> None:
    from echoprofile.server import run

    run()


def cmd_clone(args: argparse.Namespace) -> None:
    config = load_config()
    try:
        response = httpx.post(f"{config.base_url}/clone", json={"url": args.url}, timeout=60.0)
    except httpx.ConnectError:
        _connection_error(config)
        return
    _fail_on_error(response, "Clone")
    clone = response.json()
    print(f"Spun up clone {clone['id']} -> {clone['url']}")


def cmd_list(_args: argparse.Namespace) -> None:
    config = load_config()
    try:
        response = httpx.get(f"{config.base_url}/clones", timeout=10.0)
    except httpx.ConnectError:
        _connection_error(config)
        return
    _fail_on_error(response, "Listing clones")
    clones = response.json()
    if not clones:
        print("No active clones.")
        return
    for c in clones:
        print(f"{c['id']}  {c['created_at']}  {c['url']}")


def cmd_close(args: argparse.Namespace) -> None:
    config = load_config()
    try:
        response = httpx.post(f"{config.base_url}/clones/{args.clone_id}/close", timeout=10.0)
    except httpx.ConnectError:
        _connection_error(config)
        return
    if response.status_code == 404:
        print(f"No clone with id {args.clone_id!r}.")
        sys.exit(1)
    _fail_on_error(response, "Closing clone")
    print(f"Closed clone {args.clone_id}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="echoprofile")
    subparsers = parser.add_subparsers(required=True)

    p_login = subparsers.add_parser(
        "login", help="Open the persistent Edge profile (via `serve`) and keep it open for reuse"
    )
    p_login.add_argument(
        "--no-switchboard",
        action="store_true",
        help="Skip loading the Switchboard extension (loaded by default)",
    )
    p_login.set_defaults(func=cmd_login)

    p_logout = subparsers.add_parser("logout", help="Close the open persistent Edge profile")
    p_logout.set_defaults(func=cmd_logout)

    p_persistent_status = subparsers.add_parser("persistent-status", help="Show whether the persistent profile is open")
    p_persistent_status.set_defaults(func=cmd_persistent_status)

    p_seed = subparsers.add_parser(
        "seed-from-maestro", help="One-time copy of Maestro's persistent profile into echoprofile's own profile dir"
    )
    p_seed.add_argument("--force", action="store_true", help="Overwrite an existing profile dir / ignore Maestro's SingletonLock check")
    p_seed.set_defaults(func=cmd_seed_from_maestro)

    p_serve = subparsers.add_parser("serve", help="Start the background clone server")
    p_serve.set_defaults(func=cmd_serve)

    p_clone = subparsers.add_parser("clone", help="Spin up a new ephemeral clone")
    p_clone.add_argument("url", nargs="?", default=None, help="URL to open (default: configured default_url)")
    p_clone.set_defaults(func=cmd_clone)

    p_list = subparsers.add_parser("list", help="List active clones")
    p_list.set_defaults(func=cmd_list)

    p_close = subparsers.add_parser("close", help="Close an active clone")
    p_close.add_argument("clone_id")
    p_close.set_defaults(func=cmd_close)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
