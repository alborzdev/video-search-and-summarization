import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { CameraQuestionComposer } from '../CameraQuestionComposer';
it('uses warehouse prompts for a corridor-named camera and blocks presets and submission during visual monitoring', () => {
  const reason = 'Pause visual monitoring in Alert rules to ask a question.';
  const onAsk = jest.fn();
  const view = render(<CameraQuestionComposer name="Spark Hospital Corridor" canAsk={false} isLoading={false} questionBlockReason={reason} notice={reason} onAsk={onAsk} />);
  for (const name of ['Describe the scene.', 'Are people wearing PPE?', 'Is there a forklift present?']) expect(screen.getByRole('button', { name })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Ask Vision Analyst'), { target: { value: 'Keep this question' } });
  expect(screen.getByRole('button', { name: 'Send question' })).toBeDisabled();
  expect(screen.getByText(reason)).toBeInTheDocument();
  expect(onAsk).not.toHaveBeenCalled();
  view.rerender(<CameraQuestionComposer name="Spark Hospital Corridor" canAsk={true} isLoading={false} onAsk={onAsk} />);
  expect(screen.getByLabelText('Ask Vision Analyst')).toHaveValue('Keep this question');
  fireEvent.click(screen.getByRole('button', { name: 'Send question' }));
  expect(onAsk).toHaveBeenCalledWith('Keep this question');
});
