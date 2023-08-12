# Nelson Dane
# Script to Update or Initialize Project

import os
import platform
import shutil
import subprocess
import sys


def setPermsRW(path):
    # Loop through all files and folders in temp and set permissions to allow deletion
    for root, dirs, files in os.walk(path):
        for d in dirs:
            os.chmod(os.path.join(root, d), 0o777)
        for f in files:
            os.chmod(os.path.join(root, f), 0o777)


def deleteFolder(path):
    # Loop through all files and folders in temp and delete
    for root, dirs, files in os.walk(path, topdown=False):
        for f in files:
            print(f)
            os.remove(os.path.join(root, f))
        for d in dirs:
            print(d)
            os.rmdir(os.path.join(root, d))


def update_project(branch=None):
    try:
        # Check if disabled
        if os.getenv("DISABLE_AUTO_UPDATE", "").lower() == "true":
            print("Auto update disabled, skipping...")
            return
        else:
            print(
                "Starting auto update. To disable, set DISABLE_AUTO_UPDATE to true in .env"
            )
        # Check if git is installed
        try:
            subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL, check=True)
        except FileNotFoundError:
            print("Git is not installed, please install so the project can auto update")
            return
        # Get current OS
        os_name = platform.system()
        print(f"Running on {os_name}...")
        # Check if .git folder exists
        project_dir = os.path.dirname(os.path.realpath(__file__))
        if os.path.exists(os.path.join(project_dir, ".git")):
            # Get current branch
            if branch is None:
                branch = (
                    subprocess.check_output(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"]
                    )
                    .decode("utf-8")
                    .strip()
                )
            else:
                branch = branch.strip()
                # Stash all changes before switching branches
                subprocess.run(["git", "add", "."], cwd=project_dir, check=True)
                subprocess.run(["git", "stash"], cwd=project_dir, check=True)
                subprocess.run(["git", "checkout", branch], cwd=project_dir, check=True)
            print(f"Current branch: {branch}")
            # Update the project
            print("Updating project...")
            subprocess.run(
                ["git", "pull", "origin", branch], cwd=project_dir, check=True
            )
            # Restore changes
            print("Restoring changes...")
            subprocess.run(["git", "stash", "pop"], cwd=project_dir, check=True)
            print("Update complete!")
        else:
            # Check if project directory exists and is empty, remove if not
            if os.path.exists(os.path.join(project_dir, "temp")):
                setPermsRW(os.path.join(project_dir, "temp"))
                deleteFolder(os.path.join(project_dir, "temp"))
            # Clone the repository
            print("Cloning repository...")
            repo_url = "https://github.com/NelsonDane/auto-rsa"
            subprocess.run(
                ["git", "clone", repo_url, f"{project_dir}/temp", "--branch", branch],
                check=True,
            )
            # Move .git folder to initialize repository and remove temp folder
            print("Moving .git folder...")
            setPermsRW(os.path.join(project_dir, "temp"))
            shutil.move(f"{project_dir}/temp/.git", project_dir)
            deleteFolder(os.path.join(project_dir, "temp"))
            print("Repository initialized!")
            # Update the project
            update_project(branch)
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        print("Project update failed!")
        return


if __name__ == "__main__":
    branchIn = None
    if len(sys.argv) > 1:
        branchIn = sys.argv[1]
    update_project(branchIn)
