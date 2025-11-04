# Draft Archive Directory

This directory is used by the CapCut API to store draft files temporarily during the draft creation and upload process.

## Purpose

The `draft_archive` directory serves as a working directory where:
- Draft folders are created from templates
- Media assets (audio, video, images) are downloaded
- Draft information files are saved
- Zip archives are created before uploading to cloud storage

## How It Works

1. **Draft Creation**: When a draft is created, a new folder is created in this directory using the draft ID as the folder name
2. **Template Copying**: Template directories (`template` or `template_jianying`) are automatically copied here if needed
3. **Asset Download**: All media assets are downloaded to subdirectories within each draft folder
4. **Compression**: The entire draft folder is compressed into a zip file
5. **Upload**: The zip file is uploaded to cloud storage (COS)
6. **Cleanup**: After successful upload, the draft folder and zip file are automatically removed

## Directory Structure

```
draft_archive/
├── template/              # CapCut template (copied from services/template)
├── template_jianying/     # JianYing template (copied from services/template_jianying)
├── {draft_id_1}/         # Draft folder (temporary, auto-removed after upload)
│   ├── draft_info.json
│   ├── assets/
│   │   ├── audio/
│   │   ├── video/
│   │   └── image/
│   └── ...
└── {draft_id_2}/         # Another draft folder
    └── ...
```

## Important Notes

- **Automatic Cleanup**: Draft folders are automatically deleted after successful upload
- **Temporary Storage**: This directory is for temporary files only - don't store important data here
- **Git Ignored**: All files in this directory are ignored by git (see `.gitignore`)
- **Manual Cleanup**: If needed, you can safely delete the entire directory - it will be recreated automatically

## Troubleshooting

If you encounter issues:
1. Ensure the directory has write permissions
2. Check disk space availability
3. Verify that template directories exist in `services/template` or `services/template_jianying`
4. Check logs for specific error messages

## Maintenance

- No manual maintenance required - the system handles cleanup automatically
- If the directory grows too large, you can safely delete it (it will be recreated)
- Template directories are copied automatically when needed

