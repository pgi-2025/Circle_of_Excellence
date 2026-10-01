import getpass

from supabase import create_client
from config import Config


ADMIN_USER_ID = "f266595a-e89a-4fa7-9d79-3d6a6b87dfdf"
ADMIN_EMAIL = "plantgreeninertia@gmail.com"


def main():
    print("=" * 60)
    print("Circle of Excellence - Admin Password Reset")
    print("=" * 60)
    print()
    print(f"Admin email: {ADMIN_EMAIL}")
    print(f"Admin ID:    {ADMIN_USER_ID}")
    print()

    # Use the server-side Supabase credentials from Config.
    supabase = create_client(
        Config.SUPABASE_URL,
        Config.SUPABASE_SERVICE_KEY
    )

    password = getpass.getpass("Enter new admin password: ")
    confirm = getpass.getpass("Confirm new admin password: ")

    if password != confirm:
        print("\nERROR: Passwords do not match.")
        return

    if len(password) < 6:
        print("\nERROR: Password must be at least 6 characters.")
        return

    try:
        supabase.auth.admin.update_user_by_id(
            ADMIN_USER_ID,
            {
                "password": password
            }
        )

        print()
        print("=" * 60)
        print("SUCCESS: Admin password has been changed.")
        print("=" * 60)
        print()
        print(f"Email: {ADMIN_EMAIL}")
        print("You can now log in through your Admin Login page.")

    except Exception as e:
        print()
        print("=" * 60)
        print("ERROR: Could not change admin password.")
        print("=" * 60)
        print(e)


if __name__ == "__main__":
    main()