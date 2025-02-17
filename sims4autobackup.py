import json
import os.path
import logging
from datetime import datetime, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

#                   make copy of folder before testing

#                   add progress bar for each folder

SCOPES = ["https://www.googleapis.com/auth/drive"]
ACCT_DATA_FILE = "accountDataDB.package"
creds = None
gameDir = os.path.expanduser("~\\Documents\\Electronic Arts\\The Sims 4")   # default game directory, should be universal i think

# ansi codes for colored text
red = "\033[31m"
green = "\033[32m"
yellow = "\033[33m"
blue = "\033[34m"
magenta = "\033[35m"
reset = "\033[0m"       # resets to default
clearLine = "\033[K"    # clears from cursor to end of line, prevent overlapping if last line longer than current

def main():
    global creds
    global gameDir

    creds = authenticateGoogleDrive()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    # get gameDir path and backup settings from config file
    if os.path.exists("config.json"):
        with open("config.json", "r") as file:
            # prompt user to confirm/change
            configs = promptConfigs(json.load(file))
        with open("config.json", "w") as file:
            json.dump(configs, file) 
    # if no config file, apply defaults and prompt user
    else:
        defaultConfigs = {"gameDir": gameDir, "backupSaves": True, "backupTray": True, "backupAccountData": True, "backupMods": False}
        configs = promptConfigs(defaultConfigs)
        with open("config.json", "w") as file:
            json.dump(configs, file)

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
        
        if configs['backupSaves']:
            logging.info(blue + clearLine + "Uploading save files . . ." + reset)
            backupFolder(service, "saves", folderId)
        if configs['backupTray']:
            logging.info(blue + clearLine + "Uploading tray files . . ." + reset)
            backupFolder(service, "Tray", folderId)
        if configs['backupMods']:
            logging.info(blue + clearLine + "Uploading mods folder . . ." + reset)
            backupFolder(service, "Mods", folderId)           
        if configs['backupAccountData']:
        # backup accountdatadb
        # not checking modified time bc its a small enough file and seems to update every time game is closed
            logging.info(blue + clearLine + "Uploading account data file . . ." + reset)
            localdb = os.path.join(gameDir, ACCT_DATA_FILE)
            if os.path.exists(localdb) and os.path.isfile(localdb):
                response = service.files().list(q=f"'{folderId}' in parents and name='{ACCT_DATA_FILE}' and trashed=false", spaces='drive').execute()
                # update file
                if response['files']:
                    fileId = response['files'][0].get("id")
                    media = MediaFileUpload(localdb, resumable=True)
                    service.files().update(fileId=fileId, media_body=media).execute()
                    print(yellow + f"Uploaded: {os.path.basename(localdb)}" + reset, end = "\r")
                # upload as new file
                else:
                    metadata = {"name": os.path.basename(localdb), "parents": [folderId]}
                    media = MediaFileUpload(localdb, resumable=True)
                    file = service.files().create(body=metadata, media_body=media, fields="id").execute()
                    print(yellow + f"Uploaded: {os.path.basename(localdb)}" + reset, end = "\r")

        print(magenta + clearLine + "Backup complete :)" + reset)
            
    except HttpError as e:
        logging.error(red + f"Error: {str(e)}" + reset)


# need to understand this better
def authenticateGoogleDrive():
    global creds
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json")
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds

# process for saves, tray, and mods folders
def backupFolder(service, curFolder, mainFolder): 
    # implementing later bc mods folder can be different
    if curFolder == "Mods":
        logging.info(red + "Mods folder backup attempted; not yet implemented" + reset)
        return
    
    # check if folder exists, get id and datetime last modified
    response = service.files().list(q=f"'{mainFolder}' in parents and name='{curFolder}' and mimeType='application/vnd.google-apps.folder' and trashed=false", spaces='drive').execute()
    if response['files']:
        curId = response['files'][0].get("id")
    else:
        metadata = {"name": f"{curFolder}", "mimeType": "application/vnd.google-apps.folder", "parents": [mainFolder]}
        file = service.files().create(body=metadata, fields="id").execute()
        curId = file.get("id")
 
    # get last modified datetime of saves folder
    response = service.files().list(q=f"'{curId}' in parents", spaces='drive', fields="files(modifiedTime)", orderBy="modifiedTime desc").execute()

    # convert to timwzone aware datetime object for comparison
    lastModified = response['files'][0].get("modifiedTime") if response['files'] else None
    if lastModified:
        driveLastModified = datetime.fromisoformat(lastModified.replace('Z', '+00:00'))
    else:
        # set to epoch time if no files in folder
        driveLastModified = datetime.fromtimestamp(0, tz=timezone.utc)

    print(f"Last backed up: {str(driveLastModified)}", end = "\r") 

    # use os.scandir() to iterate through each folder 
    localFolder = os.path.join(gameDir, curFolder)
    for entry in os.scandir(localFolder):
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
                print(yellow + f"Updated: {entry.name}" + reset, end = "\r")

            # upload as new file
            if not response['files']:
                fileMetadata = {"name": entry.name, "parents": [curId]}
                media = MediaFileUpload(entry.path, resumable=True)
                file = service.files().create(body=fileMetadata, media_body=media, fields="id").execute()
                print(yellow + f"Uploaded: {entry.name}" + reset, end = "\r")



def promptConfigs(configs):
    global gameDir
    # gameDir saved in config file, load in beginning, if not stored try as defined in variable then this if needed
    # validate gameDir, prompt user to enter path if not found
    while not os.path.exists(gameDir):
        print(red + "The Sims 4 game directory not found.\nPlease paste the path to your game (should end in 'Documents\\Electronic Arts\\The Sims 4')" + reset)
        gameDir = input()
    # print out which files are set to backup/not
    # change the print formatting its ugly
    backupStr = ("Saves " if configs['backupSaves'] else "") + ("Tray " if configs['backupTray'] else "") + (f"{ACCT_DATA_FILE} " if configs['backupAccountData'] else "") + ("Mods " if configs['backupMods'] else "")
    noBackupStr = ("Saves " if not configs['backupSaves'] else "") + ("Tray " if not configs['backupTray'] else "") + (f"{ACCT_DATA_FILE} " if not configs['backupAccountData'] else "") + ("Mods " if not configs['backupMods'] else "")
    if backupStr:
        print("These items will be backed up: " + backupStr)
    else:
        print("No items selected for backup.")
    if noBackupStr:
        print("These items will NOT be backed up: " + noBackupStr)
    # make this so wont continue if another key is pressed
    print(blue + "Change which items to backup? (y/n)" + reset)
    change = input()
    if change.lower().strip() == 'y':
        print("Backup saves folder? (y/n)")
        configs['backupSaves'] = input().lower().strip() == 'y'
        print("Backup tray folder? (y/n)")
        configs['backupTray'] = input().lower().strip() == 'y'
        print(f"Backup {ACCT_DATA_FILE}? (y/n)")
        configs['backupAccountData'] = input().lower().strip() == 'y'
        print("Backup Mods folder? (y/n)")
        configs['backupMods'] = input().lower().strip() == 'y'
    return configs


if __name__ == "__main__":
    main()