import math, random

import numpy
import torch
import torch.nn as nn
import torch.optim as optim
import torch.autograd as autograd
import torch.nn.functional as F
import scipy.signal
import pandas

class TraceNet(nn.Module):
    def __init__(self, config, additionalFeatureSize, numActions, executionTracePredictorSize, executionFeaturePredictorSize, cursorCount):
        super(TraceNet, self).__init__()

        self.config = config

        self.stampSize = self.config['additional_features_stamp_edge_size'] * \
                         self.config['additional_features_stamp_edge_size'] * \
                         self.config['additional_features_stamp_depth_size']

        self.timeEncodingSize = 1

        self.stampProjection = nn.Sequential(
            nn.Linear(
                in_features=additionalFeatureSize,
                out_features=self.stampSize - self.timeEncodingSize
            ),
            nn.ELU(),
            nn.BatchNorm1d(num_features=self.stampSize - self.timeEncodingSize)
        )

        self.mainModel = nn.Sequential(
            nn.Conv2d(
                in_channels=1,
                out_channels=self.config['layer_1_num_kernels'],
                kernel_size=self.config['layer_1_kernel_size'], 
                stride=self.config['layer_1_stride'], 
                dilation=self.config['layer_1_dilation'], 
                padding=self.config['layer_1_padding']
            ),
            nn.ELU(),
            nn.BatchNorm2d(num_features=self.config['layer_1_num_kernels']),

            nn.Conv2d(
                in_channels=self.config['layer_1_num_kernels'],
                out_channels=self.config['layer_2_num_kernels'],
                kernel_size=self.config['layer_2_kernel_size'],
                stride=self.config['layer_2_stride'],
                dilation=self.config['layer_2_dilation'],
                padding=self.config['layer_2_padding']
            ),
            nn.ELU(),
            nn.BatchNorm2d(num_features=self.config['layer_2_num_kernels']),

            nn.Conv2d(
                in_channels=self.config['layer_2_num_kernels'],
                out_channels=self.config['layer_3_num_kernels'],
                kernel_size=self.config['layer_3_kernel_size'],
                stride=self.config['layer_3_stride'],
                dilation=self.config['layer_3_dilation'],
                padding=self.config['layer_3_padding']
            ),
            nn.ELU(),
            nn.BatchNorm2d(num_features=self.config['layer_3_num_kernels']),

            nn.Conv2d(
                in_channels=self.config['layer_3_num_kernels'],
                out_channels=self.config['pixel_features'],
                kernel_size=self.config['layer_4_kernel_size'],
                stride=self.config['layer_4_stride'],
                dilation=self.config['layer_4_dilation'],
                padding=self.config['layer_4_padding']
            ),
            nn.ELU(),
            nn.BatchNorm2d(num_features=self.config['pixel_features'])
        )

        self.stateValueLinear = nn.Sequential(
            nn.Linear(
                in_features=int(self.config['pixel_features'] * self.config['training_crop_width'] * self.config['training_crop_height'] / 64) \
                            + self.config['additional_features_stamp_depth_size'] * self.config['additional_features_stamp_edge_size'] * self.config['additional_features_stamp_edge_size'],
                out_features=self.config['layer_5_num_kernels']
            ),
            nn.ELU(),
            nn.BatchNorm1d(num_features=self.config['layer_5_num_kernels']),
            nn.Linear(
                in_features=self.config['layer_5_num_kernels'],
                out_features=1
            )
        )

        self.presentRewardConvolution = nn.Sequential(
            nn.Conv2d(
                in_channels=self.config['pixel_features'] + self.config['additional_features_stamp_depth_size'],
                out_channels=self.config['layer_5_num_kernels'],
                kernel_size=self.config['layer_5_kernel_size'],
                stride=self.config['layer_5_stride'],
                dilation=self.config['layer_5_dilation'],
                padding=self.config['layer_5_padding']
            ),
            nn.ELU(),
            nn.BatchNorm2d(num_features=self.config['layer_5_num_kernels']),
            nn.Conv2d(
                in_channels=self.config['layer_5_num_kernels'],
                out_channels=numActions,
                kernel_size=self.config['present_reward_convolution_kernel_size'],
                stride=self.config['present_reward_convolution_stride'],
                padding=self.config['present_reward_convolution_padding'],
                bias=False
            ),
            torch.nn.Upsample(scale_factor=8, mode="bilinear", align_corners=False)
        )

        self.discountedFutureRewardConvolution = nn.Sequential(
            nn.Conv2d(
                in_channels=self.config['pixel_features'] + self.config['additional_features_stamp_depth_size'],
                out_channels=self.config['layer_5_num_kernels'],
                kernel_size=self.config['layer_5_kernel_size'],
                stride=self.config['layer_5_stride'],
                dilation=self.config['layer_5_dilation'],
                padding=self.config['layer_5_padding']
            ),
            nn.ELU(),
            nn.BatchNorm2d(num_features=self.config['layer_5_num_kernels']),
            nn.Conv2d(
                in_channels=self.config['layer_5_num_kernels'],
                out_channels=numActions,
                kernel_size=self.config['discounted_future_reward_convolution_kernel_size'],
                stride=self.config['discounted_future_reward_convolution_stride'],
                padding=self.config['discounted_future_reward_convolution_padding'],
                bias=False
            ),
            torch.nn.Upsample(scale_factor=8, mode="bilinear", align_corners=False)
        )

        self.actorConvolution = nn.Sequential(
            nn.Conv2d(
                in_channels=self.config['pixel_features'] + self.config['additional_features_stamp_depth_size'],
                out_channels=self.config['layer_5_num_kernels'],
                kernel_size=self.config['layer_5_kernel_size'],
                stride=self.config['layer_5_stride'],
                dilation=self.config['layer_5_dilation'],
                padding=self.config['layer_5_padding']
            ),
            nn.ELU(),
            nn.BatchNorm2d(num_features=self.config['layer_5_num_kernels']),
            nn.Conv2d(
                in_channels=self.config['layer_5_num_kernels'],
                out_channels=numActions,
                kernel_size=self.config['actor_convolution_kernel_size'],
                stride=self.config['actor_convolution_stride'],
                padding=self.config['actor_convolution_padding'],
                bias=False
            ),
            torch.nn.Upsample(scale_factor=8, mode="bilinear", align_corners=False)
        )

        self.advantageConvolution = nn.Sequential(
            nn.Conv2d(
                in_channels=self.config['pixel_features'] + self.config['additional_features_stamp_depth_size'],
                out_channels=self.config['layer_5_num_kernels'],
                kernel_size=self.config['layer_5_kernel_size'],
                stride=self.config['layer_5_stride'],
                dilation=self.config['layer_5_dilation'],
                padding=self.config['layer_5_padding']
            ),
            nn.ELU(),
            nn.BatchNorm2d(num_features=self.config['layer_5_num_kernels']),
            nn.Conv2d(
                in_channels=self.config['layer_5_num_kernels'],
                out_channels=numActions,
                kernel_size=self.config['advantage_convolution_kernel_size'],
                stride=self.config['advantage_convolution_stride'],
                padding=self.config['advantage_convolution_padding'],
                bias=False
            ),
            torch.nn.Upsample(scale_factor=8, mode="bilinear", align_corners=False)
        )

        self.pixelFeatureMapUpsampler = nn.Sequential(
            torch.nn.Upsample(scale_factor=8, mode='bilinear', align_corners=False)
        )

        if self.config['enable_trace_prediction_loss']:
            self.predictedExecutionTraceLinear = nn.Sequential(
                nn.Linear(
                    in_features=self.config['pixel_features'] + self.config['additional_features_stamp_depth_size'],
                    out_features=executionTracePredictorSize
                ),
                nn.ELU()
            )

        if self.config['enable_execution_feature_prediction_loss']:
            self.predictedExecutionFeaturesLinear = nn.Sequential(
                nn.Linear(
                    in_features=self.config['pixel_features'] + self.config['additional_features_stamp_depth_size'],
                    out_features=executionFeaturePredictorSize
                ),
                nn.Sigmoid()
            )

        if self.config['enable_cursor_prediction_loss']:
            self.predictedCursorLinear = nn.Sequential(
                nn.Linear(
                    in_features=self.config['pixel_features'] + self.config['additional_features_stamp_depth_size'],
                    out_features=cursorCount
                ),
                nn.Sigmoid()
            )
        
        self.actionSoftmax = nn.Softmax(dim=1)

        self.numActions = numActions

    def forward(self, data):
        batchSize = data['image'].shape[0]
        width = data['image'].shape[3]
        height = data['image'].shape[2]

        pixelFeatureMap = self.mainModel(data['image'])

        # Concatenate the step number with the rest of the additional features
        additionalFeaturesWithStep = torch.cat([torch.log10(data['stepNumber'] + torch.ones_like(data['stepNumber'])).reshape([-1, 1]), self.stampProjection(data['additionalFeature'])], dim=1)

        # Append the stamp layer along side the pixel-by-pixel features
        stamp = additionalFeaturesWithStep.reshape([-1, self.config['additional_features_stamp_depth_size'],
                                                    self.config['additional_features_stamp_edge_size'],
                                                    self.config['additional_features_stamp_edge_size']])

        featureMapHeight = pixelFeatureMap.shape[2]
        featureMapWidth = pixelFeatureMap.shape[3]
        stampTiler = stamp.repeat([1, 1, int(featureMapHeight / self.config['additional_features_stamp_edge_size']) + 1, int(featureMapWidth / self.config['additional_features_stamp_edge_size']) + 1])
        stampLayer = stampTiler[:, :, :featureMapHeight, :featureMapWidth].reshape([-1, self.config['additional_features_stamp_depth_size'], featureMapHeight, featureMapWidth])

        mergedPixelFeatureMap = torch.cat([stampLayer, pixelFeatureMap], dim=1)

        outputDict = {}

        if data['computeRewards']:
            presentRewards = self.presentRewardConvolution(mergedPixelFeatureMap) * data['pixelActionMaps'] + (1.0 - data['pixelActionMaps']) * self.config['reward_impossible_action']
            discountFutureRewards = self.discountedFutureRewardConvolution(mergedPixelFeatureMap) * data['pixelActionMaps'] + (1.0 - data['pixelActionMaps']) * self.config['reward_impossible_action']

            totalReward = (presentRewards + discountFutureRewards)

            outputDict['presentRewards'] = presentRewards
            outputDict['discountFutureRewards'] = discountFutureRewards
        else:
            totalReward = None

        if data["outputStamp"]:
            outputDict["stamp"] = stamp.detach()

        if data["computeActionProbabilities"]:
            actorLogProbs = self.actorConvolution(mergedPixelFeatureMap)

            actorProbExp = torch.exp(actorLogProbs) * data['pixelActionMaps']
            actorProbSums = torch.sum(actorProbExp.reshape(shape=[-1, width * height * self.numActions]), dim=1).unsqueeze(1).unsqueeze(1).unsqueeze(1)
            actorProbSums = torch.max((actorProbSums == 0) * 1e-8, actorProbSums)
            actorActionProbs = actorProbExp / actorProbSums
            actorActionProbs = actorActionProbs.reshape([-1, self.numActions, height, width])

            outputDict["actionProbabilities"] = actorActionProbs

        if data['computeStateValues']:
            shrunkTrainingWidth = int(self.config['training_crop_width'] / 8)
            shrunkTrainingHeight = int(self.config['training_crop_width'] / 8)

            centerCropLeft = torch.div((torch.div(width, 8) - shrunkTrainingWidth), 2)
            centerCropTop = torch.div((torch.div(height, 8) - shrunkTrainingHeight), 2)

            centerCropRight = torch.add(centerCropLeft, shrunkTrainingWidth)
            centerCropBottom = torch.add(centerCropTop, shrunkTrainingHeight)

            croppedPixelFeatureMap = pixelFeatureMap[:, :, centerCropTop:centerCropBottom, centerCropLeft:centerCropRight]

            flatFeatureMap = torch.cat([additionalFeaturesWithStep.reshape(shape=[batchSize, -1]), croppedPixelFeatureMap.reshape(shape=[batchSize, -1])], dim=1)

            stateValuePredictions = self.stateValueLinear(flatFeatureMap)

            outputDict['stateValues'] = stateValuePredictions

        if data['computeAdvantageValues']:
            advantageValues = self.advantageConvolution(mergedPixelFeatureMap) * data['pixelActionMaps'] + (1.0 - data['pixelActionMaps']) * self.config['reward_impossible_action']
            outputDict['advantage'] = advantageValues

        if data['computeExtras']:
            if 'action_type' in data:
                action_types = data['action_type']
                action_xs = data['action_x']
                action_ys = data['action_y']
            else:
                action_types = []
                action_xs = []
                action_ys = []
                for sampleReward in totalReward:
                    action_type = sampleReward.reshape([self.numActions, width * height]).max(dim=1)[0].argmax(0)
                    action_types.append(action_type)

                    action_y = sampleReward[action_type].max(dim=1)[0].argmax(0)
                    action_ys.append(action_y)

                    action_x = sampleReward[action_type, action_y].argmax(0)
                    action_xs.append(action_x)

            forwardFeaturesForAuxillaryLosses = []
            for sampleIndex, action_type, action_x, action_y in zip(range(len(action_types)), action_types, action_xs, action_ys):
                featuresForAuxillaryLosses = mergedPixelFeatureMap[sampleIndex, :, int(action_y/8), int(action_x/8)].unsqueeze(0)
                forwardFeaturesForAuxillaryLosses.append(featuresForAuxillaryLosses)

            joinedFeatures = torch.cat(forwardFeaturesForAuxillaryLosses, dim=0)

            if self.config['enable_trace_prediction_loss']:
                outputDict['predictedTraces'] = self.predictedExecutionTraceLinear(joinedFeatures)
            if self.config['enable_execution_feature_prediction_loss']:
                outputDict['predictedExecutionFeatures'] = self.predictedExecutionFeaturesLinear(joinedFeatures)
            if self.config['enable_cursor_prediction_loss']:
                outputDict['predictedCursor'] = self.predictedCursorLinear(joinedFeatures)
            if self.config['enable_homogenization_loss']:
                outputDict['pixelFeatureMap'] = self.pixelFeatureMapUpsampler(mergedPixelFeatureMap)

        return outputDict


    def feature_size(self):
        return self.features(torch.zeros(1, *self.imageInputShape)).view(1, -1).size(1)
