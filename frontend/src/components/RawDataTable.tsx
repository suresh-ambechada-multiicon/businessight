import React, {
  useState,
  memo,
  useMemo,
  useEffect,
  useLayoutEffect,
  useRef,
  useDeferredValue,
  useCallback,
} from "react";
import {
  Database,
  Loader2,
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
  Search,
  X,
  Maximize2,
  Minimize2,
  AlertCircle,
} from "lucide-react";
import { api } from "../api/api";

interface RawDataTableProps {
  data: any[];
  hasData?: boolean;
  queryId?: string | number;
}

const ROW_HEIGHT = 36;
const BUFFER_ROWS = 10;

export const RawDataTable = memo(
  ({ data: initialData, hasData, queryId }: RawDataTableProps) => {
    const [lazyData, setLazyData] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [sortConfig, setSortConfig] = useState<{
      key: string | null;
      direction: "asc" | "desc" | null;
    }>({ key: null, direction: null });
    const [filters, setFilters] = useState<{ [key: string]: string }>({});
    const [activeFilters, setActiveFilters] = useState<{
      [key: string]: boolean;
    }>({});
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [scrollTop, setScrollTop] = useState(0);
    const [isExpanded, setIsExpanded] = useState(false);

    const abortRef = useRef<AbortController | null>(null);
    const headerRef = useRef<HTMLDivElement>(null);
    const bodyRef = useRef<HTMLDivElement>(null);

    const dataToUse = lazyData.length > 0 ? lazyData : (initialData || []);
    const deferredData = useDeferredValue(dataToUse);

    useEffect(() => {
      if (!isFullscreen) setScrollTop(0);
    }, [isFullscreen]);

    useEffect(() => {
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Escape" && isFullscreen) {
          setIsFullscreen(false);
        }
      };
      if (isFullscreen) {
        window.addEventListener("keydown", handleKeyDown);
      }
      return () => window.removeEventListener("keydown", handleKeyDown);
    }, [isFullscreen]);

    useEffect(() => {
      return () => abortRef.current?.abort();
    }, []);

    const hasLoadedData = dataToUse.length > 0;

    const handleToggle = (e: React.SyntheticEvent) => {
      const details = e.currentTarget as HTMLDetailsElement;
      setIsExpanded(details.open);

      if (loading) return;
      if (!details.open) return;
      if (!hasLoadedData && hasData && queryId) {
        loadData();
      }
    };

    const loadData = async () => {
      if (loading) return;

      if (abortRef.current) {
        abortRef.current.abort();
      }
      abortRef.current = new AbortController();

      setLoading(true);
      setLoadError(null);
      try {
        const result = await api.fetchQueryData(queryId!, {
          signal: abortRef.current.signal,
        });
        setLazyData(result.raw_data || []);
      } catch (error: any) {
        if (error.name === "AbortError" || error.name === "CanceledError") {
          return;
        }
        console.error("Failed to load historical data", error);
        setLoadError("Failed to load data. Please try again.");
      } finally {
        setLoading(false);
      }
    };

    const columns = useMemo(() => {
      if (deferredData.length === 0) return [];
      const keys = new Set<string>();
      deferredData.forEach((row) => {
        Object.keys(row).forEach((key) => keys.add(key));
      });
      const firstRowKeys = Object.keys(deferredData[0]);
      const additionalKeys = Array.from(keys).filter((k) => !firstRowKeys.includes(k));
      return [...firstRowKeys, ...additionalKeys];
    }, [deferredData]);

    const handleSort = (key: string) => {
      let direction: "asc" | "desc" | null = "asc";
      if (sortConfig.key === key) {
        if (sortConfig.direction === "asc") direction = "desc";
        else if (sortConfig.direction === "desc") direction = null;
      }
      setSortConfig({ key: direction ? key : null, direction });
    };

    const handleFilterChange = (key: string, value: string) => {
      setFilters((prev) => ({ ...prev, [key]: value }));
    };

    const toggleFilter = (e: React.MouseEvent, key: string) => {
      e.stopPropagation();
      setActiveFilters((prev) => ({ ...prev, [key]: !prev[key] }));
    };

    const filteredAndSortedData = useMemo(() => {
      const result = [...deferredData];

      Object.keys(filters).forEach((key) => {
        const val = filters[key].toLowerCase();
        if (val) {
          const filtered = result.filter((row) =>
            String(row[key] ?? "")
              .toLowerCase()
              .includes(val),
          );
          result.length = 0;
          result.push(...filtered);
        }
      });

      if (sortConfig.key && sortConfig.direction) {
        const { key, direction } = sortConfig;
        result.sort((a, b) => {
          const aVal = a[key];
          const bVal = b[key];
          if (aVal == null) return 1;
          if (bVal == null) return -1;

          if (typeof aVal === "number" && typeof bVal === "number") {
            return direction === "asc" ? aVal - bVal : bVal - aVal;
          }

          const aStr = String(aVal).toLowerCase();
          const bStr = String(bVal).toLowerCase();
          if (aStr < bStr) return direction === "asc" ? -1 : 1;
          if (aStr > bStr) return direction === "asc" ? 1 : -1;
          return 0;
        });
      }

      return result;
    }, [deferredData, filters, sortConfig]);

    /** Body has a vertical scrollbar; header does not — match widths so scrollLeft stays aligned. */
    const syncHeaderScrollWithBody = useCallback((body: HTMLDivElement) => {
      const header = headerRef.current;
      if (!header) return;
      header.scrollLeft = body.scrollLeft;
      const vGutter = Math.max(0, body.offsetWidth - body.clientWidth);
      header.style.paddingRight = vGutter > 0 ? `${vGutter}px` : "0px";
    }, []);

    const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
      const body = e.currentTarget;
      setScrollTop(body.scrollTop);
      syncHeaderScrollWithBody(body);
    };

    useLayoutEffect(() => {
      if (dataToUse.length === 0 || loading) return;
      const body = bodyRef.current;
      if (!body) return;

      const run = () => syncHeaderScrollWithBody(body);
      run();

      const ro = new ResizeObserver(run);
      ro.observe(body);
      window.addEventListener("resize", run);
      return () => {
        ro.disconnect();
        window.removeEventListener("resize", run);
      };
    }, [dataToUse.length, filteredAndSortedData.length, isFullscreen, loading, columns.length, syncHeaderScrollWithBody]);

    const visibleHeight = isFullscreen ? 600 : 400;
    const totalHeight = filteredAndSortedData.length * ROW_HEIGHT;
    const startIndex = Math.max(
      0,
      Math.floor(scrollTop / ROW_HEIGHT) - BUFFER_ROWS,
    );
    const endIndex = Math.min(
      filteredAndSortedData.length,
      Math.ceil((scrollTop + visibleHeight) / ROW_HEIGHT) + BUFFER_ROWS,
    );
    const visibleData = filteredAndSortedData.slice(startIndex, endIndex);
    const topPadding = startIndex * ROW_HEIGHT;

    if (!initialData && !hasData) return null;

    const Container = isFullscreen ? "div" : "details";
    const Header = isFullscreen ? "div" : "summary";

    const dataColTrackPx = isFullscreen ? 150 : 220;
    /* flex-grow so few columns fill row width; minWidth keeps readable floor + horizontal scroll when tight */
    const dataColStyle: React.CSSProperties = isFullscreen
      ? { flex: "1 1 150px", minWidth: 150 }
      : { flex: `1 1 ${dataColTrackPx}px`, minWidth: dataColTrackPx };
    const tableTrackWidth =
      columns.length === 0 ? 0 : 50 + columns.length * dataColTrackPx;

    return (
      <div
        className={`raw-data-table-wrapper ${isFullscreen ? "fullscreen" : ""}`}
      >
        <Container
          {...(!isFullscreen ? { onToggle: handleToggle } : {})}
          open={!isFullscreen ? undefined : true}
          style={
            isFullscreen
              ? {
                  display: "flex",
                  flexDirection: "column",
                  height: "100%",
                  overflow: "hidden",
                }
              : {}
          }
        >
          <Header
            className="raw-data-summary"
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
            onClick={(e) => {
              if (isFullscreen) {
                e.preventDefault();
              }
            }}
          >
            <div style={{ display: "flex", alignItems: "center" }}>
              <Database
                size={16}
                style={{ marginRight: "8px", opacity: 0.7 }}
              />
              View Data{" "}
              {dataToUse.length > 0
                ? `(${dataToUse.length.toLocaleString()} rows)`
                : hasData
                  ? "(Click to load)"
                  : ""}
            </div>

            {(dataToUse.length > 0 || isFullscreen) && (
              <button
                className="fullscreen-toggle"
                onClick={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  setIsFullscreen(!isFullscreen);
                }}
                title={isFullscreen ? "Exit Fullscreen" : "Enter Fullscreen"}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: "var(--text-secondary)",
                  display: "flex",
                  alignItems: "center",
                  padding: "4px",
                  borderRadius: "var(--radius-sm)",
                }}
              >
                {isFullscreen ? (
                  <Minimize2 size={16} />
                ) : (
                  <Maximize2 size={16} />
                )}
              </button>
            )}
          </Header>
          <div
            className={`raw-data-scroll ${loading ? "raw-data-scroll-loading" : ""}`}
          >
            {loading ? (
              <div className="loading-state">
                <Loader2 className="spinner" size={20} />
                Loading historical data...
              </div>
            ) : loadError ? (
              <div className="error-state">
                <AlertCircle size={16} />
                {loadError}
                <button
                  onClick={() => {
                    setLoadError(null);
                    const mockEvent = { target: { open: true } } as unknown as React.SyntheticEvent;
                    handleToggle(mockEvent);
                  }}
                  className="retry-btn"
                >
                  Retry
                </button>
              </div>
            ) : dataToUse.length > 0 ? (
              <div
                className="virtual-table-container"
                style={{
                  flex: isFullscreen ? 1 : "none",
                  minHeight: 0,
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                <div ref={headerRef} className="virtual-header-scroll-wrapper">
                  <div className="virtual-table-header">
                    <div className="virtual-header-cell row-num-header">#</div>
                    {columns.map((col) => (
                      <div
                        key={col}
                        className="virtual-header-cell sortable-header"
                        style={dataColStyle}
                        onClick={() => handleSort(col)}
                      >
                        <div className="header-content">
                          <span className="col-name">
                            {col.replace(/_/g, " ")}
                          </span>
                          <div className="header-actions">
                            <button
                              className={`filter-btn ${filters[col] ? "active" : ""}`}
                              onClick={(e) => toggleFilter(e, col)}
                              title="Filter column"
                            >
                              <Search size={12} />
                            </button>
                            <div className="sort-icons">
                              {sortConfig.key === col ? (
                                sortConfig.direction === "asc" ? (
                                  <ArrowUp size={12} className="active" />
                                ) : (
                                  <ArrowDown size={12} className="active" />
                                )
                              ) : (
                                <ArrowUpDown size={12} className="idle" />
                              )}
                            </div>
                          </div>
                        </div>
                        {activeFilters[col] && (
                          <div
                            className="filter-row"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <div className="filter-input-container">
                              <input
                                autoFocus
                                type="text"
                                placeholder="Search..."
                                value={filters[col] || ""}
                                onChange={(e) =>
                                  handleFilterChange(col, e.target.value)
                                }
                                onKeyDown={(e) => {
                                  if (e.key === "Escape") {
                                    setActiveFilters((prev) => ({
                                      ...prev,
                                      [col]: false,
                                    }));
                                  }
                                }}
                                className="filter-input"
                              />
                              {filters[col] && (
                                <button
                                  className="clear-filter"
                                  onClick={() => handleFilterChange(col, "")}
                                >
                                  <X size={10} />
                                </button>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
                <div
                  ref={bodyRef}
                  className="virtual-list-container"
                  style={{
                    flex: isFullscreen ? 1 : "none",
                    height: isFullscreen ? "auto" : Math.min(400, totalHeight),
                    overflowY: "auto",
                    overflowX: "auto",
                  }}
                  onScroll={handleScroll}
                >
                  <div
                    className="virtual-scroll-track"
                    style={{
                      height: totalHeight,
                      position: "relative",
                      minWidth: tableTrackWidth,
                      width: "100%",
                    }}
                  >
                    <div
                      style={{
                        position: "absolute",
                        top: topPadding,
                        left: 0,
                        width: "100%",
                      }}
                    >
                      {visibleData.map((row, idx) => (
                        <div
                          key={startIndex + idx}
                          className="virtual-row"
                          style={{
                            height: ROW_HEIGHT,
                            display: "flex",
                            width: "100%",
                          }}
                        >
                          <div className="virtual-row-number">
                            {startIndex + idx + 1}
                          </div>
                          {columns.map((col) => (
                            <div
                              key={col}
                              className="virtual-cell"
                              style={dataColStyle}
                              title={row[col] != null ? String(row[col]) : ""}
                            >
                              {row[col] != null ? String(row[col]) : "—"}
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="no-data-message">No data available.</div>
            )}
          </div>
        </Container>
      </div>
    );
  },
);