// Azure Container Apps worker: polls karaoke-jobs (same contract as local_worker.py).
// Phase 1: deployContainerApp=false — Log Analytics + ACA environment + ACR only, then `az acr build`.
// Phase 2: deployContainerApp=true + containerImage — Container App with KEDA azure-queue scale (minReplicas 0).
@description('Region for Container Apps, ACR, and Log Analytics.')
param location string = resourceGroup().location

@description('Short prefix for resource names.')
param projectName string = 'karaoke'

@description('Azure Storage connection string (same STORAGE_CONN as Function App / local_worker).')
@secure()
param storageConnectionString string

@description('When true, deploys the Container App (image must exist in ACR or registry). When false, only ACR + environment.')
param deployContainerApp bool = true

@description('Full image reference, e.g. myregistry.azurecr.io/karaoke-worker:latest')
param containerImage string = ''

@description('Queue name for KEDA and worker (must match Function App QUEUE_NAME).')
param queueName string = 'karaoke-jobs'

@description('Target messages per replica for queue scaling.')
param queueLengthPerReplica int = 1

@description('Min replicas (0 allows scale-to-zero when queue is empty).')
@minValue(0)
param minReplicas int = 0

@description('Max concurrent worker replicas.')
@minValue(1)
param maxReplicas int = 5

@description('Container vCPU (e.g. 1, 2).')
param workerCpu string = '2'

@description('Container memory, e.g. 4Gi (ratio rules apply per ACA SKU).')
param workerMemory string = '4Gi'

var suffix = uniqueString(resourceGroup().id, projectName)
var logName = '${projectName}-aca-log-${suffix}'
var envName = '${projectName}-aca-env-${suffix}'
var acrNameRaw = 'kp${replace(projectName, '-', '')}${suffix}'
var acrName = length(acrNameRaw) > 50 ? take(acrNameRaw, 50) : acrNameRaw
var appName = '${projectName}-worker-${suffix}'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// Pull credentials only when the image lives on this deployment's ACR (public images: empty registries).
var imageUsesTemplateAcr = deployContainerApp && contains(containerImage, acr.properties.loginServer)

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = if (deployContainerApp) {
  name: appName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: imageUsesTemplateAcr
        ? [
            {
              server: acr.properties.loginServer
              username: acr.listCredentials().username
              passwordSecretRef: 'acr-pull-password'
            }
          ]
        : []
      secrets: imageUsesTemplateAcr
        ? [
            {
              name: 'storage-connection'
              value: storageConnectionString
            }
            {
              name: 'acr-pull-password'
              value: acr.listCredentials().passwords[0].value
            }
          ]
        : [
            {
              name: 'storage-connection'
              value: storageConnectionString
            }
          ]
    }
    template: {
      containers: [
        {
          name: 'karaoke-worker'
          image: containerImage
          env: [
            {
              name: 'STORAGE_CONN'
              secretRef: 'storage-connection'
            }
            {
              name: 'QUEUE_NAME'
              value: queueName
            }
            {
              name: 'INPUT_CONTAINER'
              value: 'karaoke-input'
            }
            {
              name: 'OUTPUT_CONTAINER'
              value: 'karaoke-output'
            }
            {
              name: 'STATUS_CONTAINER'
              value: 'karaoke-status'
            }
            {
              name: 'OUTPUT_BASE'
              value: '/tmp/karaoke-out'
            }
            {
              name: 'QUEUE_VISIBILITY_TIMEOUT'
              value: '3600'
            }
            {
              name: 'SEPARATOR'
              value: 'spleeter'
            }
            {
              name: 'DEMUCS_MODEL'
              value: 'htdemucs_ft'
            }
            {
              name: 'LOG_LEVEL'
              value: 'INFO'
            }
          ]
          resources: {
            cpu: json(workerCpu)
            memory: workerMemory
          }
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'karaoke-jobs'
            custom: {
              type: 'azure-queue'
              metadata: {
                queueName: queueName
                queueLength: string(queueLengthPerReplica)
              }
              auth: [
                {
                  secretRef: 'storage-connection'
                  triggerParameter: 'connection'
                }
              ]
            }
          }
        ]
      }
    }
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output managedEnvironmentName string = containerAppEnv.name
output logAnalyticsWorkspaceId string = logAnalytics.id
output containerAppName string = deployContainerApp ? appName : ''
output containerAppId string = deployContainerApp ? resourceId('Microsoft.App/containerApps', appName) : ''
