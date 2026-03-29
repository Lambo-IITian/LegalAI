## LegalAI Resolver

### Email Provider

This project now uses SendGrid for all email delivery.
Azure Communication Services email is no longer used.

Required email settings:

- `SENDGRID_API_KEY`
- `SENDGRID_FROM_EMAIL`

`SENDGRID_FROM_EMAIL` must be a verified sender or verified domain in SendGrid.

### Azure App Service Deployment

Set these App Settings in Azure App Service:

- `ENVIRONMENT=production`
- `BASE_URL=<your-app-service-url>`
- `SENDGRID_API_KEY=<your-sendgrid-api-key>`
- `SENDGRID_FROM_EMAIL=<your-verified-sendgrid-from-email>`
- `AZURE_OPENAI_KEY=<...>`
- `AZURE_OPENAI_ENDPOINT=<...>`
- `AZURE_OPENAI_DEPLOYMENT_LARGE=<...>`
- `AZURE_OPENAI_DEPLOYMENT_SMALL=<...>`
- `COSMOS_CONNECTION_STRING=<...>`
- `COSMOS_DATABASE_NAME=<...>`
- `AZURE_STORAGE_CONNECTION_STRING=<...>`
- `AZURE_STORAGE_ACCOUNT_NAME=<...>`
- `CONTENT_SAFETY_KEY=<...>`
- `CONTENT_SAFETY_ENDPOINT=<...>`
- `DOC_INTELLIGENCE_KEY=<...>`
- `DOC_INTELLIGENCE_ENDPOINT=<...>`
- `JWT_SECRET_KEY=<...>`
- `JWT_ALGORITHM=HS256`
- `JWT_EXPIRE_HOURS=72`
- `OTP_EXPIRE_MINUTES=10`
- `APPINSIGHTS_INSTRUMENTATION_KEY=<optional>`

Startup command:

```bash
bash startup.sh
```

### Notes

- Do not configure `AZURE_COMM_CONNECTION_STRING` or `AZURE_SENDER_EMAIL`; they are no longer used.
- If OTP or invite emails fail in production, verify the SendGrid API key permissions and sender verification first.
