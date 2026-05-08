import React, { useState, memo, useMemo, useEffect } from "react";
import { Database, Loader2, ArrowUp, ArrowDown, ArrowUpDown, Search, X, Maximize2, Minimize2 } from "lucide-react";
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
    const [rawDataTable, setRawDataTable] = useState<any[]>(initialData || []);
    const [loading, setLoading] = useState(false);
    const [sortConfig, setSortConfig] = useState<{ key: string | null; direction: 'asc' | 'desc' | null }>({ key: null, direction: null });
    const [filters, setFilters] = useState<{ [key: string]: string }>({});
    const [activeFilters, setActiveFilters] = useState<{ [key: string]: boolean }>({});
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [scrollTop, setScrollTop] = useState(0);

    useEffect(() => {
      if (initialData) setRawDataTable(initialData);
    }, [initialData]);

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

    const handleToggle = async (e: React.SyntheticEvent) => {
      const details = e.target as HTMLDetailsElement;
      if (details.open && rawDataTable.length === 0 && hasData && queryId) {
        setLoading(true);
        try {
          const result = await api.fetchQueryData(queryId);
          setRawDataTable(result.raw_data || []);
        } catch (error) {
          console.error("Failed to load historical data", error);
        } finally {
          setLoading(false);
        }
      }
    };

    const columns = useMemo(() => 
      rawDataTable.length > 0 ? Object.keys(rawDataTable[0]) : [], 
    [rawDataTable]);

    const handleSort = (key: string) => {
      let direction: 'asc' | 'desc' | null = 'asc';
      if (sortConfig.key === key) {
        if (sortConfig.direction === 'asc') direction = 'desc';
        else if (sortConfig.direction === 'desc') direction = null;
      }
      setSortConfig({ key: direction ? key : null, direction });
    };

    const handleFilterChange = (key: string, value: string) => {
      setFilters(prev => ({ ...prev, [key]: value }));
    };

    const toggleFilter = (e: React.MouseEvent, key: string) => {
      e.stopPropagation();
      setActiveFilters(prev => ({ ...prev, [key]: !prev[key] }));
    };

    const filteredAndSortedData = useMemo(() => {
      let result = [...rawDataTable];

      Object.keys(filters).forEach(key => {
        const val = filters[key].toLowerCase();
        if (val) {
          result = result.filter(row => 
            String(row[key] ?? "").toLowerCase().includes(val)
          );
        }
      });

      if (sortConfig.key && sortConfig.direction) {
        const { key, direction } = sortConfig;
        result.sort((a, b) => {
          const aVal = a[key];
          const bVal = b[key];
          if (aVal == null) return 1;
          if (bVal == null) return -1;
          
          if (typeof aVal === 'number' && typeof bVal === 'number') {
            return direction === 'asc' ? aVal - bVal : bVal - aVal;
          }
          
          const aStr = String(aVal).toLowerCase();
          const bStr = String(bVal).toLowerCase();
          if (aStr < bStr) return direction === 'asc' ? -1 : 1;
          if (aStr > bStr) return direction === 'asc' ? 1 : -1;
          return 0;
        });
      }

      return result;
    }, [rawDataTable, filters, sortConfig]);

    const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
      setScrollTop(e.currentTarget.scrollTop);
    };

    const visibleHeight = isFullscreen ? 600 : 400;
    const totalHeight = filteredAndSortedData.length * ROW_HEIGHT;
    const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - BUFFER_ROWS);
    const endIndex = Math.min(
      filteredAndSortedData.length,
      Math.ceil((scrollTop + visibleHeight) / ROW_HEIGHT) + BUFFER_ROWS
    );
    const visibleData = filteredAndSortedData.slice(startIndex, endIndex);
    const topPadding = startIndex * ROW_HEIGHT;

    if (!initialData && !hasData) return null;

    const Container = isFullscreen ? "div" : "details";
    const Header = isFullscreen ? "div" : "summary";

    // Dynamic vertical scrollbar calculation
    const isScrollable = totalHeight > visibleHeight;
    // Standard webkit scrollbar width is typically 15px. 
    // Overlay scrollbars (macOS) will still render fine.
    const scrollbarSpacer = isScrollable ? 15 : 0;

    return (
      <div className={`raw-data-table-wrapper ${isFullscreen ? 'fullscreen' : ''}`}>
        <Container 
          {...(!isFullscreen ? { onToggle: handleToggle } : {})} 
          open={!isFullscreen ? undefined : true}
          style={isFullscreen ? { display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' } : {}}
        >
          <Header 
            className="raw-data-summary" 
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
            onClick={(e) => {
              if (isFullscreen) {
                e.preventDefault();
              }
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <Database size={16} style={{ marginRight: "8px", opacity: 0.7 }} />
              View Data{" "}
              {rawDataTable.length > 0
                ? `(${rawDataTable.length.toLocaleString()} rows)`
                : hasData
                  ? "(Click to load)"
                  : ""}
            </div>
            
            {(rawDataTable.length > 0 || isFullscreen) && (
              <button
                className="fullscreen-toggle"
                onClick={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  setIsFullscreen(!isFullscreen);
                }}
                title={isFullscreen ? "Exit Fullscreen" : "Enter Fullscreen"}
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--text-secondary)',
                  display: 'flex',
                  alignItems: 'center',
                  padding: '4px',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
              </button>
            )}
          </Header>
          <div className={`raw-data-scroll ${loading ? 'raw-data-scroll-loading' : ''}`}>
            {loading ? (
              <div className="loading-state">
                <Loader2 className="spinner" size={20} />
                Loading historical data...
              </div>
            ) : rawDataTable.length > 0 ? (
              <div className="virtual-table-container" style={{ flex: isFullscreen ? 1 : 'none', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
                <div className="virtual-header-scroll-wrapper" style={{ overflowY: isScrollable ? 'scroll' : 'hidden' }}>
                  <div className="virtual-table-header" style={{ flex: 1 }}>
                    <div className="virtual-header-cell row-num-header">#</div>
                    {columns.map((col) => (
                      <div 
                        key={col} 
                        className="virtual-header-cell sortable-header"
                        style={{ flex: '1 1 150px', minWidth: 150 }}
                        onClick={() => handleSort(col)}
                      >
                      <div className="header-content">
                        <span className="col-name">{col.replace(/_/g, " ")}</span>
                        <div className="header-actions">
                          <button 
                            className={`filter-btn ${filters[col] ? 'active' : ''}`} 
                            onClick={(e) => toggleFilter(e, col)}
                            title="Filter column"
                          >
                            <Search size={12} />
                          </button>
                          <div className="sort-icons">
                            {sortConfig.key === col ? (
                              sortConfig.direction === 'asc' ? <ArrowUp size={12} className="active" /> : <ArrowDown size={12} className="active" />
                            ) : (
                              <ArrowUpDown size={12} className="idle" />
                            )}
                          </div>
                        </div>
                      </div>
                      {activeFilters[col] && (
                        <div className="filter-row" onClick={e => e.stopPropagation()}>
                          <div className="filter-input-container">
                            <input
                              autoFocus
                              type="text"
                              placeholder="Search..."
                              value={filters[col] || ""}
                              onChange={(e) => handleFilterChange(col, e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Escape") {
                                  setActiveFilters(prev => ({ ...prev, [col]: false }));
                                }
                              }}
                              className="filter-input"
                            />
                            {filters[col] && (
                              <button className="clear-filter" onClick={() => handleFilterChange(col, "")}>
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
                  className="virtual-list-container" 
                  style={{ 
                    flex: isFullscreen ? 1 : 'none', 
                    height: isFullscreen ? 'auto' : Math.min(400, totalHeight), 
                    overflowY: 'auto', 
                    overflowX: 'hidden' 
                  }}
                  onScroll={handleScroll}
                >
                  <div style={{ height: totalHeight, position: 'relative' }}>
                    <div style={{ position: 'absolute', top: topPadding, width: '100%' }}>
                      {visibleData.map((row, idx) => (
                        <div 
                          key={startIndex + idx} 
                          className="virtual-row"
                          style={{ height: ROW_HEIGHT, display: 'flex', width: '100%' }}
                        >
                          <div className="virtual-row-number">{startIndex + idx + 1}</div>
                          {columns.map((col) => (
                            <div 
                              key={col} 
                              className="virtual-cell" 
                              style={{ flex: '1 1 150px', minWidth: 150 }}
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
                {filteredAndSortedData.length > 0 && (
                  <div className="virtual-footer">
                    Showing {filteredAndSortedData.length.toLocaleString()} rows (virtualized) | Scroll to load more
                  </div>
                )}
              </div>
            ) : (
              <div className="no-data-message">
                No data available.
              </div>
            )}
          </div>
        </Container>
      </div>
    );
  },
);