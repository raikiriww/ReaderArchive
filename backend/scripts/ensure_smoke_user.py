from __future__ import annotations

import argparse

from app.core.config import Settings
from app.crud import UserRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensure a stable admin user for smoke tests.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    repository = UserRepository(Settings().database_url)
    existing_user = repository.get_user_by_username(args.username)
    if existing_user is None:
        repository.create_user(args.username, args.password, "admin")
        return

    repository.update_user(existing_user.id, enabled=True, role="admin")
    repository.reset_password(existing_user.id, args.password)


if __name__ == "__main__":
    main()
