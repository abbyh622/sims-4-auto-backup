import json
import os.path
import logging
import tqdm
from datetime import datetime, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# make 'saves', 'Tray', 'Mods' global or something, currently weird

SCOPES = ["https://www.googleapis.com/auth/drive"]
ACCT_DATA_FILE = "accountDataDB.package"
DEFAULT_CONFIGS = {"gameDir": "C:\\Users\\abbyh\\Documents\\Electronic Arts\\The Sims 4", "items": {"saves": True, "Tray": False, "accountDataDB": True, "Mods": False}}
creds = None
gameDir = os.path.expanduser("~\\Documents\\Electronic Arts\\The Sims 4")   # default game directory, should be universal i think

# ansi codes for colored text
red = "\033[31m"
green = "\033[32m"
yellow = "\033[33m"
magenta = "\033[35m"
ltblue = "\033[36m"
reset = "\033[0m"       # resets to default
clearLine = "\033[K"    # clears from cursor to end of line, prevent overlapping if last line longer than current

def main():
    global creds
    global gameDir

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    creds = authenticateGoogleDrive()
    
    # get gameDir path and backup settings from config file
    if os.path.exists("config.json"):
        with open("config.json", "r") as file:
            # prompt user to confirm/change
            configs = promptConfigs(json.load(file))
        with open("config.json", "w") as file:
            json.dump(configs, file) 
    # if no config file, apply defaults and prompt user
    else:
        configs = promptConfigs(DEFAULT_CONFIGS)
        with open("config.json", "w") as file:
            json.dump(configs, file)
    backupItems = configs['items']

    try:
        service = build("drive", "v3", credentials=creds)
        # if backup folder exists, get id and datetime last modified
        # need to specify trashed=false otherwise it will include trashed folders
        response = service.files().list(q="name='Sims 4 Backup' and mimeType='application/vnd.google-apps.folder' and trashed=false", spaces='drive').execute()
        if response['files']:   # response is a dictionary
            folderId = response['files'][0].get("id")
            logging.info("Backup folder found")
        # else create backup folder
        else: 
            metadata = {"name": "Sims 4 Backup", "mimeType": "application/vnd.google-apps.folder"}
            file = service.files().create(body=metadata, fields="id").execute()
            folderId = file.get("id")
            logging.info("Backup folder not found; created new folder")

        if backupItems['saves']:
            logging.info(ltblue + clearLine + "Uploading save files . . ." + reset)
            backupFolder(service, "saves", folderId)
        if backupItems['Tray']:
            logging.info(ltblue + clearLine + "Uploading tray files . . ." + reset)
            backupFolder(service, "Tray", folderId)
        if backupItems['Mods']:
            logging.info(ltblue + clearLine + "Uploading mods folder . . ." + reset)
            backupFolder(service, "Mods", folderId)           
        if backupItems['accountDataDB']:
        # backup accountdatadb
        # not checking modified time bc its a small enough file and seems to update every time game is closed
            logging.info(ltblue + clearLine + "Uploading account data file . . ." + reset)
            localdb = os.path.join(gameDir, ACCT_DATA_FILE)
            if os.path.exists(localdb) and os.path.isfile(localdb):
                response = service.files().list(q=f"'{folderId}' in parents and name='{ACCT_DATA_FILE}' and trashed=false", spaces='drive').execute()
                # update file
                if response['files']:
                    fileId = response['files'][0].get("id")
                    media = MediaFileUpload(localdb, resumable=True)
                    service.files().update(fileId=fileId, media_body=media).execute()
                    print(yellow + f"Uploaded: {ACCT_DATA_FILE}" + reset, end = "\r")
                # upload as new file
                else:
                    metadata = {"name": ACCT_DATA_FILE, "parents": [folderId]}
                    media = MediaFileUpload(localdb, resumable=True)
                    file = service.files().create(body=metadata, media_body=media, fields="id").execute()
                    print(yellow + f"Uploaded: {os.path.basename(ACCT_DATA_FILE)}" + reset, end = "\r")
            else:
                logging.error(red + f"Error: {os.path.basename(ACCT_DATA_FILE)} not found" + reset)

        print(green + clearLine + "Backup complete :)" + reset)
            
    except HttpError as e:
        logging.error(red + f"Error: {str(e)}" + reset)


# need to understand this better
def authenticateGoogleDrive():
    global creds
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        # if creds expired, refresh token
        if creds and creds.expired and creds.refresh_token:
            logging.info("Refreshing token . . .")
            try:
                creds.refresh(Request())
            # if refresh fails, delete token file and reauthenticate
            except Exception as e:
                logging.error(red + f"Error refreshing token: {str(e)}" + reset)
                os.remove("token.json")
                creds = None
        # if no creds, get new token (promps user to authenticate in browser)
        if not creds:
            logging.info("Authenticating. . .")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
            # save token
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds


# process for saves, tray, and mods folders
def backupFolder(service, curFolder, mainFolder): 

    if curFolder == "Mods":
        print(red + "Mods folder backup not yet implemented" + reset)
        return
    
    # check if folder exists, get id and datetime last modified
    response = service.files().list(q=f"'{mainFolder}' in parents and name='{curFolder}' and mimeType='application/vnd.google-apps.folder' and trashed=false", spaces='drive').execute()
    if response['files']:
        curId = response['files'][0].get("id")
    else:
        metadata = {"name": f"{curFolder}", "mimeType": "application/vnd.google-apps.folder", "parents": [mainFolder]}
        file = service.files().create(body=metadata, fields="id").execute()
        curId = file.get("id")
 
    # get last modified datetime of drive folder
    response = service.files().list(q=f"'{curId}' in parents", spaces='drive', fields="files(modifiedTime)", orderBy="modifiedTime desc").execute()

    # convert to timwzone aware datetime object for comparison
    lastModified = response['files'][0].get("modifiedTime") if response['files'] else None
    if lastModified:
        driveLastModified = datetime.fromisoformat(lastModified.replace('Z', '+00:00'))
    else:
        # set to epoch time if no files in folder
        driveLastModified = datetime.fromtimestamp(0, tz=timezone.utc)
    # print(f"Last backed up: {str(driveLastModified)}") 
    
    localFolder = os.path.join(gameDir, curFolder)  # get local folder path             
    # get number of files in folder for progress bar
    numFiles = len(os.listdir(localFolder))                                     # dont think this will be right for mods folder bc nested folders

    # use os.scandir() to iterate through each folder 
    for entry in tqdm.tqdm(os.scandir(localFolder), total=numFiles, position=0):
        # get last modified time
        if entry.is_file():
            localLastModified = datetime.fromtimestamp(os.path.getmtime(entry.path), tz=timezone.utc)
            # check if file exists in drive
            response = service.files().list(q=f"'{curId}' in parents and name='{entry.name}' and trashed=false", spaces='drive').execute()
            # update file
            if response['files'] and localLastModified > driveLastModified:
                fileId = response['files'][0].get("id")
                media = MediaFileUpload(entry.path, resumable=True)
                service.files().update(fileId=fileId, media_body=media).execute()
                # print(yellow + f"Updated: {entry.name}" + reset, end = "\r")
            # upload as new file
            if not response['files']:
                fileMetadata = {"name": entry.name, "parents": [curId]}
                media = MediaFileUpload(entry.path, resumable=True)
                file = service.files().create(body=fileMetadata, media_body=media, fields="id").execute()
                # print(yellow + f"Uploaded: {entry.name}" + reset, end = "\r")


def promptConfigs(configs):
    global gameDir
    # gameDir saved in config file, load in beginning, if not stored try as defined in variable then this if needed
    # validate gameDir, prompt user to enter path if not found
    while not os.path.exists(gameDir):
        print(red + "The Sims 4 game directory not found.\nPlease paste the path to your game (should end in 'Documents\\Electronic Arts\\The Sims 4')" + reset)
        gameDir = input()

    # get lists of items to/not backup and print
    backupItems = configs['items']
    willBackup = [k for k,v in backupItems.items() if v]
    wontBackup = [k for k,v in backupItems.items() if not v]
    willBackupStr = ", ".join(willBackup)
    wontBackupStr = ", ".join(wontBackup)
    if willBackupStr:
        print("These items will be backed up: " + green + willBackupStr + reset)
        if wontBackupStr:
            print("These items will NOT be backed up: " + red + wontBackupStr + reset)
    else:
        print("No items selected for backup.")

    # make this so wont continue if another key is pressed
    print(ltblue + "Change which items to backup? (y/n)" + reset)
    change = input()
    if change.lower().strip() == 'y':
        print("Backup saves folder? (y/n)")
        backupItems['saves'] = input().lower().strip() == 'y'
        print("Backup tray folder? (y/n)")
        backupItems['Tray'] = input().lower().strip() == 'y'
        print(f"Backup {ACCT_DATA_FILE}? (y/n)")
        backupItems['accountDataDB'] = input().lower().strip() == 'y'
        print("Backup Mods folder? (y/n)")
        backupItems['Mods'] = input().lower().strip() == 'y'
    return configs


if __name__ == "__main__":
    main()