declare const ELK: {
  new (args?: {
    defaultLayoutOptions?: Record<string, string>;
    algorithms?: string[];
    workerUrl?: string;
    workerFactory?: (url?: string) => Worker;
  }): {
    layout<T extends { id: string; children?: T[] }>(
      graph: T,
      args?: {
        layoutOptions?: Record<string, string>;
        logging?: boolean;
        measureExecutionTime?: boolean;
      },
    ): Promise<T>;
    terminateWorker(): void;
    knownLayoutAlgorithms(): Promise<unknown[]>;
    knownLayoutOptions(): Promise<unknown[]>;
    knownLayoutCategories(): Promise<unknown[]>;
  };
};

export default ELK;
