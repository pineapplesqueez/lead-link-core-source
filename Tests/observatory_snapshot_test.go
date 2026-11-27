package observatory

import (
	"context"
	"errors"
	"sync"
	"testing"
)

func TestLeadLinkSnapshotsSurviveConcurrentUpdates(t *testing.T) {
	collector := newErrorCollector()
	collector.SubmitError(errors.New("first"))
	firstError := collector.UnderlyingError()
	firstText := firstError.Error()
	observer := &Observer{}
	observer.updateStatusForResult("edge", &ProbeResult{Alive: true, Delay: 7})
	first, err := observer.GetObservation(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	initial := first.(*ObservationResult).Status[0]

	var workers sync.WaitGroup
	for i := 0; i < 4; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for j := 0; j < 100; j++ {
				collector.SubmitError(errors.New("later"))
				_ = collector.UnderlyingError().Error()
				observer.updateStatusForResult("edge", &ProbeResult{LastErrorReason: "offline"})
				snapshot, err := observer.GetObservation(context.Background())
				if err != nil || len(snapshot.(*ObservationResult).Status) != 1 {
					t.Error("expected a complete status snapshot")
					return
				}
				if initial.Delay != 7 || !initial.Alive || firstError.Error() != firstText {
					t.Error("an already returned snapshot changed")
					return
				}
			}
		}()
	}
	workers.Wait()
}
