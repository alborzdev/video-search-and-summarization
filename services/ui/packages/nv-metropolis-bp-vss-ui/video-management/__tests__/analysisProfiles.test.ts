import { loadAnalysisProfiles } from '../lib-src/analysisProfiles';

it('explains an unavailable profile service instead of exposing proxy HTML', async () => {
  global.fetch = jest.fn().mockResolvedValue({ok:false,status:503,text:async()=>'<html><body><h1>503 Service Unavailable</h1>No server is available</body></html>'});
  await expect(loadAnalysisProfiles('/agent')).rejects.toThrow('Analysis profiles are unavailable. Check System, then reopen this form to retry.');
});

it('preserves a structured service explanation', async () => {
  global.fetch = jest.fn().mockResolvedValue({ok:false,status:409,text:async()=>JSON.stringify({detail:'Analysis is busy.'})});
  await expect(loadAnalysisProfiles('/agent')).rejects.toThrow('Analysis is busy.');
});
