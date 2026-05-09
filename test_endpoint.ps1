# Test the WhatsApp Flow endpoint locally
$body = @{
    action = "ping"
} | ConvertTo-Json

Write-Host "Testing local endpoint..." -ForegroundColor Yellow

try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/flow/flow-endpoint" `
        -Method POST `
        -ContentType "application/json" `
        -Body $body

    Write-Host "Status: $($response.StatusCode)" -ForegroundColor Green
    Write-Host "Response: $($response.Content)" -ForegroundColor Green
    Write-Host "✅ Local endpoint works!" -ForegroundColor Green
} catch {
    Write-Host "❌ Error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Make sure the server is running first!" -ForegroundColor Red
}

Read-Host "Press Enter to exit"