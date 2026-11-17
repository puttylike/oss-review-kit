import * as cdk from 'aws-cdk-lib';
import { ShowcaseStack } from '../lib/showcase-stack';

const app = new cdk.App();

new ShowcaseStack(app, 'OssReviewKitShowcase', {
  stackName: 'OssReviewKitShowcase',
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'us-east-1',
  },
});
