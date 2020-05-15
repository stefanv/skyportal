import * as API from '../API';
import store from '../store';


export const FETCH_CANDIDATE = 'skyportal/FETCH_CANDIDATE';
export const FETCH_CANDIDATE_OK = 'skyportal/FETCH_CANDIDATE_OK';
export const FETCH_CANDIDATE_FAIL = 'skyportal/FETCH_CANDIDATE_FAIL';

export const fetchCandidate = (id) => (
  API.GET(`/api/candidates/${id}`, FETCH_CANDIDATE)
);

const initialState = {
  candidate: null
};

const reducer = (state = initialState, action) => {
  switch (action.type) {
    case FETCH_CANDIDATE_OK: {
      const { candidate } = action.data;
      return {
        ...state,
        candidate
      };
    }
    default:
      return state;
  }
};

store.injectReducer('candidate', reducer);
