# Getting Started

This is a step-by-step walkthrough for someone who has just cloned the repo and never touched Azure before. If you already know your way around `az`, jump straight to the README.

## What you need on your laptop

- **Python 3.11** (3.12 also works but the wheels for stable-baselines3 are flakier)
- **Docker Desktop** running
- **Azure CLI** version 2.60 or newer (`az --version`)
- A free Azure account, ideally [Azure for Students](https://azure.microsoft.com/en-us/free/students/) which gives $100 in credits and no credit card required

## Part 1: Run it locally without Azure

You can get the API running on your laptop in five minutes, no cloud needed.

```bash
git clone https://github.com/Demba-SowAchta/tradeon.git
cd tradeon

python -m venv .venv
# Windows:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -r api/requirements.txt
```

If you don't have a trained PPO weights file, build a stub one so the API can boot:

```bash
python - << 'EOF'
import joblib, sys
sys.path.insert(0, 'api')
from app.rl_service import StubAgent
joblib.dump(StubAgent(), 'api/artifacts/ppo_v1.0.0.pkl')
print("stub agent saved")
EOF
```

Now launch the API:

```bash
# Windows PowerShell:
$env:MODEL_PATH = "$pwd\api\artifacts\ppo_v1.0.0.pkl"
cd api
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# macOS / Linux:
export MODEL_PATH=$(pwd)/api/artifacts/ppo_v1.0.0.pkl
cd api && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000/docs in your browser. You should see Swagger UI with four endpoints. Try `GET /health` — it should return `{"status":"ok","agent_loaded":true}`.

## Part 2: Test with real market data

Open a second terminal (keep the API running in the first).

```bash
pip install -r scripts/requirements.txt

# Quickest test: use the SPY CSV that ships with the repo
python scripts/live_predict.py --url http://localhost:8000 --csv test_spy.csv

# Pull fresh data from Yahoo Finance instead
python scripts/live_predict.py --url http://localhost:8000 --symbol SPY --n-bars 100

# Test on three tickers at once
python scripts/live_predict.py --url http://localhost:8000 --symbols SPY,AAPL,TSLA
```

You'll see a colored summary with cumulative return, Sharpe ratio, win rate, plus a tiny ASCII equity curve.

## Part 3: Deploy to Azure (the first time)

This part assumes you have an Azure subscription with credits left. The whole thing takes about 15 minutes the first time.

### 3.1 Log in and set context

```bash
az login                                      # opens a browser
az account list -o table                      # find your subscription name
az account set --subscription "<your-sub>"

# Pick a region close to you
$env:RG  = "rg-rlpipeline-dev"               # or use Linux RG=...
$env:LOC = "francecentral"
```

### 3.2 Register the resource providers you'll need

Azure subscriptions don't have these enabled by default:

```bash
foreach ($p in @("Microsoft.Storage","Microsoft.App","Microsoft.ContainerRegistry","Microsoft.DocumentDB","Microsoft.EventGrid","Microsoft.Web","Microsoft.OperationalInsights","Microsoft.Insights")) {
  az provider register --namespace $p
}
```

Wait until `az provider show -n Microsoft.App --query registrationState` returns `Registered`. Usually 30 seconds.

### 3.3 Run the Bicep template

```bash
az group create -n $env:RG -l $env:LOC
az deployment group create -g $env:RG -f infrastructure/bicep/main.bicep -p envName=dev
```

This creates 9 resources: storage account, container registry, cosmos free tier, log analytics, app insights, container apps environment, container app (with a placeholder image), function app, event grid system topic + subscription.

When it finishes, copy the output names:

```bash
$env:ACR_NAME      = az acr list -g $env:RG --query "[0].name" -o tsv
$env:CONTAINER_APP = "rl-api"
$env:FUNC_APP      = az functionapp list -g $env:RG --query "[0].name" -o tsv
$env:COSMOS_NAME   = az cosmosdb list -g $env:RG --query "[0].name" -o tsv
```

### 3.4 Push your Docker image

```bash
az acr login -n $env:ACR_NAME
docker build -t "$($env:ACR_NAME).azurecr.io/rl-api:v1" ./api
docker push "$($env:ACR_NAME).azurecr.io/rl-api:v1"
```

The first build downloads ~700 MB of layers (PyTorch is heavy). After that, only your changes get pushed.

### 3.5 Point the Container App at the image

```bash
az containerapp update -n rl-api -g $env:RG `
  --image "$($env:ACR_NAME).azurecr.io/rl-api:v1"
```

Wait 30 seconds, then:

```bash
$FQDN = az containerapp show -n rl-api -g $env:RG --query properties.configuration.ingress.fqdn -o tsv
curl "https://$FQDN/health"
# Expected: {"status":"ok","agent_loaded":true,"load_time_ms":...}
```

### 3.6 Deploy the Functions

You'll need Azure Functions Core Tools v4:

```bash
npm install -g azure-functions-core-tools@4 --unsafe-perm true
```

Then:

```bash
cd functions
func azure functionapp publish $env:FUNC_APP --python
cd ..
```

### 3.7 Set the Function App settings

The functions need the Cosmos connection string and the RL API URL. Get them and inject them:

```bash
$COSMOS_CONN = az cosmosdb keys list -n $env:COSMOS_NAME -g $env:RG --type connection-strings --query "connectionStrings[0].connectionString" -o tsv
$RL_API_URL  = "https://$FQDN"

az functionapp config appsettings set -n $env:FUNC_APP -g $env:RG --settings `
  "COSMOS_CONN=$COSMOS_CONN" `
  "COSMOS_DB=rlpipeline" `
  "COSMOS_CONTAINER=episodes" `
  "RL_API_URL=$RL_API_URL" `
  "QUEUE_NAME=rl-jobs" `
  "INPUT_CONTAINER=input" `
  "OUTPUT_CONTAINER=output" `
  "REJECTED_CONTAINER=rejected"
```

### 3.8 If Event Grid doesn't fire

This is the most common gotcha on Consumption plan. Do this:

```bash
az functionapp restart -g $env:RG -n $env:FUNC_APP
$SUB = az account show --query id -o tsv
az rest --method post --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$env:RG/providers/Microsoft.Web/sites/$env:FUNC_APP/syncfunctiontriggers?api-version=2016-08-01"
Start-Sleep -Seconds 90
```

Then re-create the Event Grid subscription (Bicep created one but it might point to a stale function endpoint after the publish):

```bash
$STORAGE_ID = az storage account list -g $env:RG --query "[0].id" -o tsv
$FUNC_ID    = az functionapp function show -g $env:RG -n $env:FUNC_APP --function-name dispatcher --query id -o tsv

az eventgrid event-subscription delete --name csv-uploaded --source-resource-id $STORAGE_ID 2>$null
az eventgrid event-subscription create `
  --name csv-uploaded `
  --source-resource-id $STORAGE_ID `
  --endpoint-type azurefunction `
  --endpoint $FUNC_ID `
  --included-event-types Microsoft.Storage.BlobCreated `
  --subject-begins-with "/blobServices/default/containers/input/"
```

### 3.9 Trigger the full pipeline end-to-end

```bash
# Upload a CSV to the input container
$STORAGE = az storage account list -g $env:RG --query "[0].name" -o tsv
az storage blob upload -f test_spy.csv -c input -n "test_$(Get-Date -Format yyyyMMddHHmmss).csv" --account-name $STORAGE --auth-mode login
```

Within 30 seconds you should see:
- A new blob in the `output` container with `_result.json` suffix
- A new document in Cosmos DB `rlpipeline.episodes`
- An entry in the dashboard at https://<your-static-web-app>.azurestaticapps.net

If something didn't fire, check the Function App's `Live Metrics` in Application Insights.

## Part 4: CI/CD on GitHub

Once your local deploy works, set up automatic deployment.

```bash
# Run the setup script that creates a service principal with OIDC
bash .github/cicd/setup_cicd.sh
```

The script prints three secrets to add to GitHub (Settings → Secrets and variables → Actions):
- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

And four variables in the same page (Variables tab):
- `RG=rg-rlpipeline-dev`
- `CONTAINER_APP=rl-api`
- `FUNC_APP=<your function app name>`
- `ACR_NAME=<your acr name>`

Then create a GitHub environment called `staging` (Settings → Environments → New environment). No approval gates needed for staging.

Push to main and watch the Actions tab. The smoke test at the end retries `/health` up to 15 times with 5-second pauses — give it a minute on cold starts.

## Cleaning up

After the defence, kill everything to stop billing:

```bash
az group delete --name rg-rlpipeline-dev --yes --no-wait
```

That single command deletes 9 resources at once. It takes about 5 minutes in the background.
