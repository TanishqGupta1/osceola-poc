import os
import sys

from dotenv import load_dotenv

load_dotenv()

from s3_operations import (
    delete_object,
    download_file,
    list_buckets,
    list_objects,
    read_object,
    upload_file,
)


def get_bucket_name():
    return os.environ.get("S3_BUCKET_NAME") or input("Enter bucket name: ").strip()


def menu():
    print("\n--- AWS S3 Operations ---")
    print("1. List all buckets")
    print("2. List objects in bucket")
    print("3. Upload a file")
    print("4. Download a file")
    print("5. Read file content")
    print("6. Delete a file")
    print("7. Exit")
    return input("\nSelect an option (1-7): ").strip()


def main():
    required_vars = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        print(f"Error: Missing environment variables: {', '.join(missing)}")
        print("Set them or copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    while True:
        choice = menu()

        if choice == "1":
            buckets = list_buckets()
            if buckets:
                print(f"\nFound {len(buckets)} bucket(s):")
                for b in buckets:
                    print(f"  - {b['Name']} (created: {b['CreationDate']})")
            else:
                print("No buckets found.")

        elif choice == "2":
            bucket = get_bucket_name()
            prefix = input("Enter prefix (or leave blank): ").strip()
            objects = list_objects(bucket, prefix)
            if objects:
                print(f"\nFound {len(objects)} object(s):")
                for obj in objects:
                    print(f"  - {obj['Key']} ({obj['Size']} bytes)")
            else:
                print("No objects found.")

        elif choice == "3":
            bucket = get_bucket_name()
            file_path = input("Enter local file path: ").strip()
            key = input("Enter S3 key (or leave blank for filename): ").strip() or None
            upload_file(file_path, bucket, key)

        elif choice == "4":
            bucket = get_bucket_name()
            key = input("Enter S3 key to download: ").strip()
            file_path = input("Enter local save path (or leave blank): ").strip() or None
            download_file(bucket, key, file_path)

        elif choice == "5":
            bucket = get_bucket_name()
            key = input("Enter S3 key to read: ").strip()
            content = read_object(bucket, key)
            if content:
                print(f"\n--- Content of {key} ---")
                print(content.decode("utf-8", errors="replace"))

        elif choice == "6":
            bucket = get_bucket_name()
            key = input("Enter S3 key to delete: ").strip()
            confirm = input(f"Delete '{key}' from '{bucket}'? (y/n): ").strip().lower()
            if confirm == "y":
                delete_object(bucket, key)
            else:
                print("Cancelled.")

        elif choice == "7":
            print("Goodbye!")
            break

        else:
            print("Invalid option. Try again.")


if __name__ == "__main__":
    main()
