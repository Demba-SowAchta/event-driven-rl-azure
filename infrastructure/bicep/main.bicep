// Bicep RL Pipeline - usage: az deployment group create -g <rg> -f main.bicep -p envName=dev
@description('Environment name')
param envName string = 'dev'
@description('Azure region')
param location string = resourceGroup().location

var suffix = uniqueString(resourceGroup().id, envName)
var storageName = 'strlpipe${envName}${take(suffix, 6)}'
var acrName     = 'acrrlpipe${envName}${take(suffix, 6)}'
var cosmosName  = 'cosmos-rlpipe-${envName}-${take(suffix, 6)}'
var lawName     = 'law-rlpipe-${envName}'
var appiName    = 'appi-rlpipe-${envName}'
var caeName     = 'cae-rlpipe-${envName}'

resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: lawName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 }
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: appiName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { minimumTlsVersion: 'TLS1_2', allowBlobPublicAccess: false }
}

resource blobSvc 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storage
  name: 'default'
  properties: { isVersioningEnabled: true }
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = [for c in [
  'input','output','models','rejected'
]: {
  parent: blobSvc
  name: c
  properties: { publicAccess: 'None' }
}]

resource qSvc 'Microsoft.Storage/storageAccounts/queueServices@2023-01-01' = {
  parent: storage
  name: 'default'
}

resource queues 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-01-01' = [for q in [
  'rl-jobs','rl-jobs-poison'
]: {
  parent: qSvc
  name: q
}]

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2023-11-15' = {
  name: cosmosName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    enableFreeTier: true
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location, failoverPriority: 0 }]
    databaseAccountOfferType: 'Standard'
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-11-15' = {
  parent: cosmos
  name: 'rlpipeline'
  properties: { resource: { id: 'rlpipeline' } }
}

resource cosmosCtr 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-11-15' = {
  parent: cosmosDb
  name: 'episodes'
  properties: {
    resource: {
      id: 'episodes'
      partitionKey: { paths: ['/agent_version'], kind: 'Hash' }
    }
    options: { throughput: 400 }
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: true }
}

resource cae 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: caeName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

output storageName string = storage.name
output cosmosName string = cosmos.name
output acrLogin string = acr.properties.loginServer
output appInsightsConn string = appi.properties.ConnectionString
