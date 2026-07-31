// SPDX-License-Identifier: MIT
import { render, screen, act } from '@testing-library/react';
import { DashboardComponent } from '../lib-src/DashboardComponent';

describe('DashboardComponent', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    act(() => {
      jest.runOnlyPendingTimers();
    });
    jest.useRealTimers();
  });

  it('shows error when kibanaBaseUrl is not configured', () => {
    render(<DashboardComponent dashboardData={{ kibanaBaseUrl: null }} />);
    expect(
      screen.getByText(/Kibana base URL is not configured/i),
    ).toBeInTheDocument();
  });

  it('shows error when kibanaBaseUrl is empty string', () => {
    render(<DashboardComponent dashboardData={{ kibanaBaseUrl: '' }} />);
    expect(
      screen.getByText(/Kibana base URL is not configured/i),
    ).toBeInTheDocument();
  });

  it('renders loading state with a valid URL', () => {
    render(
      <DashboardComponent
        dashboardData={{ kibanaBaseUrl: 'https://kibana.example.com' }}
      />,
    );
    expect(screen.getByText('Loading dashboard...')).toBeInTheDocument();
  });

  it('applies dark theme classes', () => {
    const { container } = render(
      <DashboardComponent
        theme="dark"
        dashboardData={{ kibanaBaseUrl: null }}
      />,
    );
    expect(container.firstChild).toHaveClass('bg-black');
  });

  it('does not remount the iframe when isActive toggles off and on after first load', () => {
    const dashboardData = {
      kibanaBaseUrl: 'https://kibana.example.com',
      dashboards: [] as const,
    };
    const { rerender } = render(
      <DashboardComponent isActive={false} dashboardData={dashboardData} />,
    );
    expect(screen.queryByTitle('Kibana Dashboard')).not.toBeInTheDocument();

    rerender(<DashboardComponent isActive dashboardData={dashboardData} />);
    const iframe = screen.getByTitle('Kibana Dashboard');
    act(() => {
      iframe.dispatchEvent(new Event('load'));
    });

    rerender(<DashboardComponent isActive={false} dashboardData={dashboardData} />);
    rerender(<DashboardComponent isActive dashboardData={dashboardData} />);

    expect(screen.getByTitle('Kibana Dashboard')).toBe(iframe);
  });

  it('does not warn about an iframe fallback before the Dashboard tab is opened', () => {
    const warning = jest.spyOn(console, 'warn').mockImplementation(() => undefined);

    render(
      <DashboardComponent
        isActive={false}
        dashboardData={{ kibanaBaseUrl: 'https://kibana.example.com' }}
      />,
    );
    act(() => {
      jest.advanceTimersByTime(10_000);
    });

    expect(screen.queryByTitle('Kibana Dashboard')).not.toBeInTheDocument();
    expect(warning).not.toHaveBeenCalled();
    warning.mockRestore();
  });

  it('silently shows the iframe when its load event does not fire', () => {
    const warning = jest.spyOn(console, 'warn').mockImplementation(() => undefined);

    render(
      <DashboardComponent
        dashboardData={{ kibanaBaseUrl: 'https://kibana.example.com' }}
      />,
    );
    expect(screen.getByTitle('Kibana Dashboard')).toHaveStyle({ display: 'none' });

    act(() => {
      jest.advanceTimersByTime(10_000);
    });

    expect(screen.getByTitle('Kibana Dashboard')).toHaveStyle({ display: 'block' });
    expect(warning).not.toHaveBeenCalled();
    warning.mockRestore();
  });

  it('uses Kibana embed mode and safely encodes a selected dashboard id', () => {
    render(
      <DashboardComponent
        dashboardData={{
          kibanaBaseUrl: 'https://kibana.example.com/kibana',
          dashboards: [
            { id: 'warehouse/dashboard', attributes: { title: 'Warehouse' } },
          ],
        }}
      />,
    );

    const iframe = screen.getByTitle('Kibana Dashboard');
    expect(iframe).toHaveAttribute(
      'src',
      'https://kibana.example.com/kibana/app/dashboards#/view/warehouse%2Fdashboard?embed=true',
    );
  });

  it('selects the configured default dashboard when it is available', () => {
    render(
      <DashboardComponent
        dashboardData={{
          kibanaBaseUrl: 'https://kibana.example.com/kibana',
          defaultDashboardId: 'thor-vss-overview',
          dashboards: [
            { id: 'warehouse', attributes: { title: 'Warehouse' } },
            { id: 'thor-vss-overview', attributes: { title: 'Thor VSS Overview' } },
          ],
        }}
      />,
    );

    expect(screen.getByTitle('Kibana Dashboard')).toHaveAttribute(
      'src',
      'https://kibana.example.com/kibana/app/dashboards#/view/thor-vss-overview?embed=true',
    );
  });
});
