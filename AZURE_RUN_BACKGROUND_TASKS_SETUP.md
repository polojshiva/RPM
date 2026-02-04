# Setting RUN_BACKGROUND_TASKS in Azure Web App

## Overview
Simple approach: Background tasks (message poller and ClinicalOps processor) only run if `RUN_BACKGROUND_TASKS=true` is set.

**How it works:**
- Set `RUN_BACKGROUND_TASKS=true` for ONE worker only
- That worker will run background tasks
- Other workers won't run background tasks

**For 4 workers: Use Azure Deployment Slots**
- Create a separate deployment slot for background tasks
- Set `RUN_BACKGROUND_TASKS=true` only in that slot (1 worker)
- Set `RUN_BACKGROUND_TASKS=false` in production slot (4 workers for API)

---

## Method 1: Azure Portal (Recommended)

### Step 1: Navigate to Configuration
1. Go to [Azure Portal](https://portal.azure.us)
2. Navigate to your App Service: **`prd-wiser-ops-appb`**
3. In the left menu, click **Configuration**

### Step 2: Add Application Setting
1. Click **+ New application setting**
2. Enter:
   - **Name:** `RUN_BACKGROUND_TASKS`
   - **Value:** `true` (for the instance that should run background tasks)
3. Click **OK**

### Step 3: Save and Restart
1. Click **Save** at the top
2. Azure will prompt to restart - click **Continue**
3. Or manually restart: **Overview** → **Restart**

### For Multiple Instances (Scale Out)
If you have multiple instances (e.g., 4 workers):

**Instance 1 (Primary):**
- `RUN_BACKGROUND_TASKS` = `true`

**Instance 2, 3, 4:**
- `RUN_BACKGROUND_TASKS` = `false` (or leave unset)

**Note:** Azure App Service doesn't support per-instance settings directly. You have two options:

#### Option A: Single Instance for Background Tasks (Recommended)
- Set `RUN_BACKGROUND_TASKS=true` globally
- Only one instance will actually run (the first one that starts)
- This is safe because the code checks the flag at startup

#### Option B: Use Deployment Slots
- Create a separate deployment slot for background tasks
- Set `RUN_BACKGROUND_TASKS=true` only in that slot
- Set `RUN_BACKGROUND_TASKS=false` in production slot

---

## Method 2: Azure CLI

### Set for All Instances (One will run)
```bash
az webapp config appsettings set \
  --resource-group <your-resource-group> \
  --name prd-wiser-ops-appb \
  --settings RUN_BACKGROUND_TASKS=true
```

### Remove/Unset (if needed)
```bash
az webapp config appsettings delete \
  --resource-group <your-resource-group> \
  --name prd-wiser-ops-appb \
  --setting-names RUN_BACKGROUND_TASKS
```

### Verify Setting
```bash
az webapp config appsettings list \
  --resource-group <your-resource-group> \
  --name prd-wiser-ops-appb \
  --query "[?name=='RUN_BACKGROUND_TASKS']"
```

---

## Method 3: Azure PowerShell

### Set
```powershell
$resourceGroup = "<your-resource-group>"
$appName = "prd-wiser-ops-appb"

az webapp config appsettings set `
  --resource-group $resourceGroup `
  --name $appName `
  --settings RUN_BACKGROUND_TASKS=true
```

---

## Method 4: ARM Template / Bicep (Infrastructure as Code)

### ARM Template
```json
{
  "type": "Microsoft.Web/sites/config",
  "apiVersion": "2021-02-01",
  "name": "[concat(parameters('appServiceName'), '/appsettings')]",
  "properties": {
    "RUN_BACKGROUND_TASKS": "true"
  }
}
```

### Bicep
```bicep
resource appSettings 'Microsoft.Web/sites/config@2021-02-01' = {
  name: '${appServiceName}/appsettings'
  properties: {
    RUN_BACKGROUND_TASKS: 'true'
  }
}
```

---

## Verification

### 1. Check Logs
After setting and restarting, check application logs:

**Azure Portal:**
- **Log stream** → Look for:
  - `✅ Message poller started (interval: 180s, batch_size: 7, worker_id: <id>)`
  - `✅ ClinicalOps inbox processor started (interval: 120s, batch_size: 2, worker_id: <id>)`

**For workers without the flag:**
- `Message poller not started - RUN_BACKGROUND_TASKS is not enabled`

### 2. Health Check Endpoint
```bash
curl https://prd-wiser-ops-appb.azurewebsites.us/health/poller
```

Expected response (when running):
```json
{
  "status": "healthy",
  "poller_running": true,
  "poller_enabled": true,
  "run_background_tasks": true,
  "worker_id": "worker-<uuid>"
}
```

Expected response (when not running):
```json
{
  "status": "stopped",
  "poller_running": false,
  "poller_enabled": true,
  "run_background_tasks": false,
  "worker_id": "worker-<uuid>"
}
```

---

## Important Notes

### ⚠️ Single Instance Requirement
- **Only ONE instance should have `RUN_BACKGROUND_TASKS=true`**
- If multiple instances have it set to `true`, they will all try to run background tasks (duplicate processing)
- If no instances have it set to `true`, background tasks won't run

### 🔄 Restart Required
- Environment variable changes require an app restart
- Azure Portal will prompt you to restart after saving
- Or restart manually: **Overview** → **Restart**

### 📊 Monitoring
- Monitor `/health/poller` endpoint to verify poller is running
- Check application logs for startup messages
- Use Application Insights to track poller activity

### 🚀 Deployment
- If using CI/CD, you can set this in your deployment pipeline
- Or set it once in Azure Portal and it will persist across deployments

---

## Troubleshooting

### Poller Not Starting
1. **Check environment variable:**
   ```bash
   az webapp config appsettings list \
     --resource-group <rg> \
     --name prd-wiser-ops-appb \
     --query "[?name=='RUN_BACKGROUND_TASKS']"
   ```

2. **Check logs:**
   - Look for: `RUN_BACKGROUND_TASKS is not enabled for this instance`
   - Or: `Message poller is disabled in settings`

3. **Verify restart:**
   - Ensure app was restarted after setting the variable

### Multiple Pollers Running
- Check if multiple instances have `RUN_BACKGROUND_TASKS=true`
- Set to `false` for all except one instance
- Restart all instances

### No Poller Running
- Verify `RUN_BACKGROUND_TASKS=true` is set
- Check `message_poller_enabled` setting (should be `true`)
- Check application logs for errors

---

## Current Configuration Recommendation

For your 4-worker setup:

**Recommended:** Use Azure Deployment Slots:
- **Production slot:** 4 workers, `RUN_BACKGROUND_TASKS=false` (API only)
- **Background slot:** 1 worker, `RUN_BACKGROUND_TASKS=true` (background tasks only)

**Alternative:** If you can't use slots, set `RUN_BACKGROUND_TASKS=true` globally and accept that all 4 workers will run background tasks (may cause duplicate processing).
