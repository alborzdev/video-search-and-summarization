import type { GetServerSideProps, NextApiHandler, NextApiRequest, NextApiResponse } from 'next';

export interface ApiWrapperOptions {
  allowedMethods?: string[];
  bodyParserConfig?: {
    sizeLimit?: string;
  };
}

export type EdgeApiHandler = (request: Request) => Promise<Response>;

export const getNemoAgentToolkitSSProps: GetServerSideProps;
export const chatApiHandler: NextApiHandler;

export function createApiWrapper(
  edgeHandler: EdgeApiHandler,
  options?: ApiWrapperOptions,
): (request: NextApiRequest, response: NextApiResponse) => Promise<void>;

export function createChatApiWrapper(
  edgeHandler: EdgeApiHandler,
): (request: NextApiRequest, response: NextApiResponse) => Promise<void>;
