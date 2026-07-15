from __future__ import annotations

import pytest


@pytest.fixture
def sample_rdl() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition">
  <Description>Sanitized claims report</Description>
  <DataSources>
    <DataSource Name="Main"><ConnectionProperties><DataProvider>SQL</DataProvider><ConnectString>Data Source=example;User ID=test;Password=secret</ConnectString></ConnectionProperties></DataSource>
  </DataSources>
  <DataSets>
    <DataSet Name="Claims">
      <Query><DataSourceName>Main</DataSourceName><QueryParameters><QueryParameter Name="@CompCode"><Value>=Parameters!CompCode.Value</Value></QueryParameter></QueryParameters><CommandText>SELECT ClaimID, Amount
FROM dbo.Claims
WHERE CompCode = @CompCode</CommandText></Query>
      <Fields><Field Name="ClaimID"><DataField>ClaimID</DataField></Field><Field Name="Amount"><DataField>Amount</DataField></Field></Fields>
      <Filters><Filter><FilterExpression>=Fields!Amount.Value</FilterExpression></Filter></Filters>
    </DataSet>
  </DataSets>
  <ReportParameters><ReportParameter Name="CompCode"><DataType>String</DataType><Prompt>Company</Prompt></ReportParameter></ReportParameters>
  <Tablix><TablixMember><Group Name="Company"><GroupExpressions><GroupExpression>=Fields!CompCode.Value</GroupExpression></GroupExpressions></Group></TablixMember></Tablix>
</Report>"""
