import React from 'react';
import PropTypes from 'prop-types';
import { connect } from 'react-redux';

import * as Action from '../actions';

import SourceList from '../components/SourceList';
import UninitializedDBMessage from '../components/UninitializedDBMessage';


class SourceListContainer extends React.Component {
  componentDidMount() {
    if (!this.props.sources) {
      this.props.dispatch(Action.fetchSources());
    }
  }

  render() {
    if (this.props.sourcesTableEmpty) {
      return <UninitializedDBMessage />;
    }
    if (this.props.sources) {
      return <SourceList sources={this.props.sources} />;
    } else {
      return "Loading sources...";
    }
  }
}

SourceListContainer.propTypes = {
  dispatch: PropTypes.func.isRequired,
  sources: PropTypes.arrayOf(PropTypes.object),
  sourcesTableEmpty: PropTypes.bool
};

SourceListContainer.defaultProps = {
  sources: null,
  sourcesTableEmpty: false
};

const mapStateToProps = (state, ownProps) => (
  {
    sources: state.sources.latest,
    sourcesTableEmpty: state.sysinfo.sources_table_empty
  }
);

export default connect(mapStateToProps)(SourceListContainer);
