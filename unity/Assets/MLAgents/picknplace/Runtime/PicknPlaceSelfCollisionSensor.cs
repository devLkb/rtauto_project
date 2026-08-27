using UnityEngine;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// Detects the robot's own links touching each other (e.g. a finger crossing
    /// into another finger, or the hand folding into the forearm).
    ///
    /// This intentionally does NOT reuse the robot's physical colliders or
    /// <c>RobotSelfCollisionIgnore</c>'s ignore-pair table: that component disables
    /// PhysX collision *response* between every pair of robot colliders (all of
    /// them, not just adjacent links) to avoid the contact-jitter limit cycle from
    /// geometrically-overlapping adjacent phalanges/wrist-mount parts (see its own
    /// doc comment). Re-enabling physical response for a subset of pairs would risk
    /// reintroducing that jitter for the whole robot, in every scene that shares the
    /// prefab. Instead, each instrumented collider grows a same-shaped trigger
    /// "shadow" collider (see PicknPlaceTrainingSceneBuilder.AddTriggerShadow) that
    /// only reports overlaps — <c>Physics.IgnoreCollision</c> does not suppress
    /// trigger callbacks, so this detects real geometric overlap without touching
    /// physics response at all.
    ///
    /// A contact only counts as a violation when the two owning links are not the
    /// same body and not directly connected by a joint (parent/child in the
    /// ArticulationBody chain) — adjacent links are expected to overlap by design.
    /// </summary>
    public sealed class PicknPlaceSelfCollisionSensor : MonoBehaviour
    {
        public ArticulationBody owningBody;

        public bool HasViolation { get; private set; }

        public void ResetContacts()
        {
            HasViolation = false;
        }

        void OnTriggerEnter(Collider other) => Evaluate(other);

        void OnTriggerStay(Collider other) => Evaluate(other);

        void Evaluate(Collider other)
        {
            if (other == null) return;
            var otherSensor = other.GetComponent<PicknPlaceSelfCollisionSensor>();
            if (otherSensor == null || otherSensor.owningBody == null || owningBody == null) return;
            if (IsSelfCollision(owningBody, otherSensor.owningBody)) HasViolation = true;
        }

        public static bool IsSelfCollision(ArticulationBody a, ArticulationBody b)
        {
            if (a == null || b == null || a == b) return false;
            return ImmediateParentBody(a) != b && ImmediateParentBody(b) != a;
        }

        static ArticulationBody ImmediateParentBody(ArticulationBody body)
        {
            if (body == null) return null;
            for (Transform t = body.transform.parent; t != null; t = t.parent)
            {
                var parentBody = t.GetComponent<ArticulationBody>();
                if (parentBody != null) return parentBody;
            }
            return null;
        }
    }
}
