// SPDX-License-Identifier: MIT
import { GetServerSideProps } from 'next';
import Head from 'next/head';

import VisionIntelligenceApp from '../components/vision-intelligence/VisionIntelligenceApp';
import {
  emptyInitialVisionPageData,
  getInitialVisionPageData,
} from '../server/vision/initialPageData';

// Server-side props with data fetching
export const getServerSideProps: GetServerSideProps = async (context) => {
  try {
    const { getNemoAgentToolkitSSProps } = await import('@nemo-agent-toolkit/ui/server');
    const initialVisionData = import('@nv-metropolis-bp-vss-ui/all/server')
      .then(({ fetchAlertsData, fetchSearchData, fetchVideoManagementData }) =>
        getInitialVisionPageData({
          alerts: fetchAlertsData,
          search: fetchSearchData,
          videoManagement: fetchVideoManagementData,
        })
      )
      .catch((error) => {
        console.error('Error fetching Vision Intelligence data:', error);
        return emptyInitialVisionPageData();
      });

    // Keep the toolkit's translations/redirect semantics independent of the
    // optional workspace data sources.
    const nemoResult = await getNemoAgentToolkitSSProps(context);

    // Preserve redirects and not-found responses from the embedded toolkit.
    // Only the props result can be merged into this page's props.
    if (!('props' in nemoResult)) {
      return nemoResult;
    }
    const [nemoProps, visionData] = await Promise.all([
      nemoResult.props,
      initialVisionData,
    ]);
    
    // Chain/Merge all props
    return {
      props: {
        ...nemoProps,              // Spread NemoAgentToolkit props (i18n, etc.)
        ...visionData,
        serverRenderTime: new Date().toISOString(),
      },
    };
  } catch (error) {
    console.error('Error in getServerSideProps:', error);
    
    // Fallback: return minimal props if fetching fails
    return {
      props: {
        ...emptyInitialVisionPageData(),
        serverRenderTime: new Date().toISOString(),
      },
    };
  }
};

// Props interface matching what getServerSideProps returns
interface HomePageProps {
  alertsData?: any;
  searchData?: any;
  videoManagementData?: any;
  serverRenderTime?: string;
}

export default function HomePage(props: HomePageProps) {
  // Pass all SSR props to Home component
  return (
    <>
      <Head>
        <title>Vision Intelligence</title>
      </Head>
      <VisionIntelligenceApp {...props} />
    </>
  );
}
