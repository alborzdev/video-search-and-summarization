// SPDX-License-Identifier: MIT
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { CityEdgePage, deploymentBrief } from '../CityEdgePage';
const requirements={siteType:'Signalized intersection',cameras:2,priorities:['Turning traffic'],retention:'Discuss with the team',notes:'  Site A  '};
test('requirements are bounded and never sold as capacity or accuracy evidence',()=>{
 for(const cameras of [0,1.5,NaN,10001]) expect(deploymentBrief({...requirements,cameras})).toBeNull();
 expect(deploymentBrief({...requirements,priorities:[]})).toBeNull();expect(deploymentBrief({...requirements,priorities:['Unknown']})).toBeNull();
 const brief=deploymentBrief(requirements)!;expect(brief.requirements.notes).toBe('Site A');expect(brief.scope).toContain('not a hardware quote');expect(brief.scope).toContain('accuracy');
});
test('workflow routes visitors to evidence and a local pilot form',()=>{
 const onView=jest.fn(),onReview=jest.fn();render(<CityEdgePage cameraCount={2} liveCameraCount={1} onView={onView} onReview={onReview}/>);
 expect(screen.getByText('2 configured cameras · 1 live')).toBeInTheDocument();fireEvent.click(screen.getByRole('button',{name:/03 Review/}));expect(onReview).toHaveBeenCalledTimes(1);
 fireEvent.click(screen.getByRole('button',{name:'Build a deployment brief'}));expect(screen.getByRole('heading',{name:'Plan an edge AI pilot'})).toBeInTheDocument();fireEvent.change(screen.getByLabelText('Planned camera count'),{target:{value:'0'}});expect(screen.getByRole('button',{name:'Download discussion brief'})).toBeDisabled();
});
