import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3n from 'aws-cdk-lib/aws-s3-notifications';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';

export class ShowcaseStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const myKitDir: string =
      this.node.tryGetContext('myKitDir') ?? path.join(os.homedir(), 'claude-lab/capstone/my-kit');
    const modelId: string = this.node.tryGetContext('modelId') ?? 'us.anthropic.claude-sonnet-5-5';
    const foundationModelId = modelId.replace(/^(us|eu|apac|global)\./, '');

    // ---------------------------------------------------------------- 정적 사이트
    // 비공개 버킷: 퍼블릭 액세스 전면 차단, CloudFront(OAC)로만 읽기 허용
    const bucket = new s3.Bucket(this, 'SiteBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true, // DESTROY만으로는 객체가 남은 버킷을 지우지 못함
    });

    // ---------------------------------------------------------------- 실행 데이터
    // 작업 상태, 결과, 하루 카운터. 사이트 버킷과 분리해 CloudFront로 노출되지 않고
    // BucketDeployment의 prune에 지워지지 않게 한다.
    const dataBucket = new s3.Bucket(this, 'DataBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [
        { prefix: 'jobs/', expiration: cdk.Duration.days(30) },
        { prefix: 'cache/', expiration: cdk.Duration.days(2) },
        { prefix: 'counters/', expiration: cdk.Duration.days(7) },
      ],
    });

    // 실행 역할: Bedrock 모델 호출과 데이터 버킷 접근만 (로그 권한도 주지 않음)
    const role = new iam.Role(this, 'ReviewFnRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'oss-review runner: bedrock:InvokeModel + data bucket only',
    });
    role.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: [
        `arn:${this.partition}:bedrock:${this.region}:${this.account}:inference-profile/${modelId}`,
        // 교차 리전 추론 프로필은 실제로 여러 리전의 기반 모델로 라우팅된다
        `arn:${this.partition}:bedrock:*::foundation-model/${foundationModelId}`,
      ],
    }));
    role.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject', 's3:PutObject', 's3:DeleteObject'],
      resources: [dataBucket.arnForObjects('*')],
    }));
    role.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:ListBucket'], // 없는 키를 403이 아닌 NoSuchKey로 받고, 직전 리포트를 찾는 데 필요
      resources: [dataBucket.bucketArn],
    }));

    const handlerDir = path.join(__dirname, '../lambda/review');
    const promptFiles = collectPromptFiles(myKitDir);

    const fn = new lambda.Function(this, 'ReviewFn', {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: 'handler.handler',
      role,
      timeout: cdk.Duration.minutes(15),
      memorySize: 512,
      retryAttempts: 0, // 실패는 상태 파일에 남기고 자동 재시도로 한도를 더 쓰지 않는다
      code: lambda.Code.fromAsset(handlerDir, {
        // 출력물 기준 해시: my-kit 지시문만 바뀌어도 새 코드로 배포된다
        assetHashType: cdk.AssetHashType.OUTPUT,
        bundling: {
          image: lambda.Runtime.PYTHON_3_13.bundlingImage,
          local: {
            tryBundle(outputDir: string) {
              fs.copyFileSync(path.join(handlerDir, 'handler.py'), path.join(outputDir, 'handler.py'));
              for (const [rel, src] of promptFiles) {
                const dst = path.join(outputDir, 'prompts', rel);
                fs.mkdirSync(path.dirname(dst), { recursive: true });
                fs.copyFileSync(src, dst);
              }
              return true;
            },
          },
        },
      }),
      environment: {
        DATA_BUCKET: dataBucket.bucketName,
        MODEL_ID: modelId,
        DAILY_LIMIT: '20',
      },
    });

    // request.json이 생기면 S3가 이 함수를 비동기로 호출한다 (실행 역할에 lambda:Invoke 불필요).
    // 함수가 쓰는 status.json, report.md는 접미사가 달라 다시 트리거하지 않는다.
    dataBucket.addEventNotification(
      s3.EventType.OBJECT_CREATED_PUT,
      new s3n.LambdaDestination(fn),
      { prefix: 'jobs/', suffix: '/request.json' },
    );

    // CloudFront만 호출할 수 있는 Function URL (OAC가 SigV4로 서명)
    const fnUrl = fn.addFunctionUrl({ authType: lambda.FunctionUrlAuthType.AWS_IAM });

    const distribution = new cloudfront.Distribution(this, 'SiteDistribution', {
      defaultRootObject: 'index.html',
      defaultBehavior: {
        // OAC 생성 + 버킷 정책에 배포 ARN(SourceArn) 조건으로 s3:GetObject 부여
        origin: origins.S3BucketOrigin.withOriginAccessControl(bucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        compress: true,
      },
      additionalBehaviors: {
        '/api/*': {
          origin: origins.FunctionUrlOrigin.withOriginAccessControl(fnUrl),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          // Host를 넘기면 OAC 서명이 깨지므로 Host만 빼고 전달
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
      },
      priceClass: cloudfront.PriceClass.PRICE_CLASS_200,
    });

    new s3deploy.BucketDeployment(this, 'DeploySite', {
      sources: [s3deploy.Source.asset(path.join(__dirname, '../../frontend'))],
      destinationBucket: bucket,
      distribution, // 업로드 후 캐시 무효화
      distributionPaths: ['/*'],
      prune: true,
    });

    new cdk.CfnOutput(this, 'CloudFrontURL', {
      value: cdk.Fn.join('', ['https://', distribution.distributionDomainName]),
      description: 'Showcase site URL',
    });
    new cdk.CfnOutput(this, 'BucketName', { value: bucket.bucketName });
    new cdk.CfnOutput(this, 'DataBucketName', { value: dataBucket.bucketName });
  }
}

/** my-kit의 SKILL.md와 agents/*.md를 [Lambda 안 상대 경로, 원본 경로] 목록으로. 없으면 synth를 멈춘다. */
function collectPromptFiles(myKitDir: string): Array<[string, string]> {
  const files: Array<[string, string]> = [];
  const skill = path.join(myKitDir, 'skills/oss-review/SKILL.md');
  if (!fs.existsSync(skill)) throw new Error(`SKILL.md를 찾지 못했습니다: ${skill} (-c myKitDir=... 로 지정)`);
  files.push(['skills/oss-review/SKILL.md', skill]);

  const agentsDir = path.join(myKitDir, 'agents');
  const agents = fs.existsSync(agentsDir) ? fs.readdirSync(agentsDir).filter((f) => f.endsWith('.md')) : [];
  for (const need of ['mcp-researcher.md', 'evidence-reviewer.md']) {
    if (!agents.includes(need)) throw new Error(`에이전트 지시문이 없습니다: ${path.join(agentsDir, need)}`);
  }
  for (const f of agents) files.push([`agents/${f}`, path.join(agentsDir, f)]);
  return files;
}
