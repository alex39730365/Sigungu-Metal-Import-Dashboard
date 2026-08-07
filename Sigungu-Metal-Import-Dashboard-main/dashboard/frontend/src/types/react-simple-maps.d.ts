declare module "react-simple-maps" {
  import * as React from "react";

  export interface ComposableMapProps extends React.SVGProps<SVGSVGElement> {
    projection?: string | ((width: number, height: number, config?: any) => any);
    projectionConfig?: Record<string, unknown>;
    width?: number;
    height?: number;
    viewBox?: string;
  }
  export const ComposableMap: React.FC<ComposableMapProps>;

  export interface Geography {
    rsmKey: string;
    properties: Record<string, unknown>;
    [key: string]: any;
  }

  export interface GeographiesRenderProps {
    geographies: Geography[];
  }
  export interface GeographiesProps {
    geography: string | Record<string, unknown> | any;
    children: (props: GeographiesRenderProps) => React.ReactNode;
  }
  export const Geographies: React.FC<GeographiesProps>;

  export interface GeographyProps {
    geography: Geography;
    fill?: string;
    stroke?: string;
    strokeWidth?: number;
    [key: string]: any;
  }
  export const Geography: React.FC<GeographyProps>;

  export interface MarkerProps extends React.SVGProps<SVGGElement> {
    coordinates: [number, number];
    onClick?: () => void;
  }
  export const Marker: React.FC<MarkerProps>;
}
